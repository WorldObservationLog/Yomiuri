import asyncio
from http.cookies import SimpleCookie

import click
import socketio
from bilibili_api import Credential
from bilibili_api.live import LiveDanmaku
from loguru import logger
from tenacity import retry, wait_fixed, retry_if_exception_type

from yomiuri.models import Available, Actions

loop = asyncio.get_event_loop()
sio = socketio.AsyncClient(reconnection=True, reconnection_delay=3, reconnection_delay_max=3, logger=logger)
bili_cookies = ""
danmu_client = {}


@click.command()
@click.option("--url", default="http://127.0.0.1:12345/yomiuri", help="Yomiuri服务地址")
@click.option("--cookies", help="Bilibili Cookies, 形如bili_jct=XXX;SESSDATA=XXX;dedeuserid=XXX;buvid3=XXX")
def cli(url, cookies):
    global bili_cookies
    bili_cookies = cookies
    loop.create_task(first_connect(url))
    loop.run_forever()


@retry(wait=wait_fixed(3), retry=retry_if_exception_type(socketio.exceptions.ConnectionError))
async def first_connect(url):
    try:
        await sio.connect(url)
    except socketio.exceptions.ConnectionError as e:
        logger.warning("Can't connect to Yomiuri server! Retry after 3 seconds...")
        raise e


@sio.event()
async def connect():
    if bool(danmu_client):
        await sio.emit(Actions.Available, Available(status=False, room_id=list(danmu_client.keys())[0]).model_dump())
    else:
        await sio.emit(Actions.Available, Available(status=True).model_dump())
    logger.info("Yomiuri server connected!")


@sio.on(Actions.StartListening)
async def start_listening(data):
    room_id = data["room_id"]
    parsed_cookies = SimpleCookie()
    parsed_cookies.load(bili_cookies)
    credential = Credential(bili_jct=parsed_cookies["bili_jct"].value,
                            buvid3=parsed_cookies["buvid3"].value,
                            sessdata=parsed_cookies["sessdata"].value,
                            dedeuserid=parsed_cookies["deaduserid"].value)

    async def handle_danmu(danmu):
        await sio.emit(Actions.Danmu, danmu)

    client = LiveDanmaku(room_id, credential=credential)
    client.add_event_listener("__ALL__", handle_danmu)
    danmu_client[room_id] = client
    loop.create_task(client.connect())
    logger.info(f"Start listening room {room_id}")


@sio.on(Actions.StopListening)
async def stop_listening(data):
    room_id = data["room_id"]
    client = danmu_client[room_id]
    await client.disconnect()
    del danmu_client[room_id]
    await sio.emit(Actions.Available, Available(status=True).model_dump())
    logger.info(f"Stop listening room {room_id}")


@sio.event()
async def disconnect():
    logger.warning("Disconnected from Yomiuri server! Retrying...")
