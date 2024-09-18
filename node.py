import asyncio
import requests
import json
import time
import uuid
import os
from loguru import logger

# 상수
USER_ID = os.getenv('userid')
NP_TOKEN = os.getenv('nptoken')
PING_INTERVAL = 30  # 초
RETRIES = 60  # 핑 실패에 대한 전역 재시도 카운터

DOMAIN_API = {
    "SESSION": "https://api.nodepay.ai/api/auth/session",
    "PING": "https://nw2.nodepay.ai/api/network/ping"
}

CONNECTION_STATES = {
    "CONNECTED": 1,
    "DISCONNECTED": 2,
    "NONE_CONNECTION": 3
}

status_connect = CONNECTION_STATES["NONE_CONNECTION"]
token_info = NP_TOKEN
browser_id = None
account_info = {}

def uuidv4():
    return str(uuid.uuid4())

def valid_resp(resp):
    if not resp or "code" not in resp or resp["code"] < 0:
        raise ValueError("유효하지 않은 응답")
    return resp

async def render_profile_info(proxy):
    global browser_id, token_info, account_info

    try:
        np_session_info = load_session_info(proxy)

        if not np_session_info:
            response = call_api(DOMAIN_API["SESSION"], {}, proxy)
            valid_resp(response)
            account_info = response["data"]
            if account_info.get("uid"):
                save_session_info(proxy, account_info)
                await start_ping(proxy)
            else:
                handle_logout(proxy)
        else:
            account_info = np_session_info
            await start_ping(proxy)
    except Exception as e:
        logger.error(f"{proxy}에서 render_profile_info 중 오류 발생: {e}")
        error_message = str(e)
        if any(phrase in error_message for phrase in [
            "sent 1011 (internal error) keepalive ping timeout; no close frame received",
            "500 Internal Server Error"
        ]):
            logger.info(f"오류가 발생한 프록시 목록에서 제거: {proxy}")
            remove_proxy_from_list(proxy)
            return None
        else:
            logger.error(f"연결 오류: {e}")
            return proxy

def call_api(url, data, proxy):
    headers = {
        "Authorization": f"Bearer {token_info}",
        "Content-Type": "application/json"
    }

    try:
        response = requests.post(url, json=data, headers=headers, proxies={"http": proxy, "https": proxy}, timeout=10)
        response.raise_for_status()
    except requests.RequestException as e:
        logger.error(f"API 호출 중 오류 발생: {e}")
        raise ValueError(f"{url}에 대한 API 호출 실패")

    return valid_resp(response.json())

async def start_ping(proxy):
    try:
        await ping(proxy)
        while True:
            await asyncio.sleep(PING_INTERVAL)
            await ping(proxy)
    except asyncio.CancelledError:
        logger.info(f"{proxy}의 핑 작업이 취소됨")
    except Exception as e:
        logger.error(f"{proxy}의 start_ping 중 오류 발생: {e}")

async def ping(proxy):
    global RETRIES, status_connect

    try:
        data = {
            "id": account_info.get("uid"),
            "browser_id": browser_id,
            "timestamp": int(time.time())
        }

        response = call_api(DOMAIN_API["PING"], data, proxy)
        if response["code"] == 0:
            logger.info(f"{proxy}를 통한 핑 성공: {response}")
            RETRIES = 0
            status_connect = CONNECTION_STATES["CONNECTED"]
        else:
            handle_ping_fail(proxy, response)
    except Exception as e:
        logger.error(f"{proxy}를 통한 핑 실패: {e}")
        handle_ping_fail(proxy, None)

def handle_ping_fail(proxy, response):
    global RETRIES, status_connect

    RETRIES += 1
    if response and response.get("code") == 403:
        handle_logout(proxy)
    elif RETRIES < 2:
        status_connect = CONNECTION_STATES["DISCONNECTED"]
    else:
        status_connect = CONNECTION_STATES["DISCONNECTED"]

def handle_logout(proxy):
    global token_info, status_connect, account_info

    token_info = None
    status_connect = CONNECTION_STATES["NONE_CONNECTION"]
    account_info = {}
    save_status(proxy, None)
    logger.info(f"{proxy}에 대한 로그아웃 및 세션 정보 삭제 완료")

def load_proxies(proxy_file):
    try:
        with open(proxy_file, 'r') as file:
            proxies = file.read().splitlines()
        return proxies
    except Exception as e:
        logger.error(f"프록시 로드 실패: {e}")
        raise SystemExit("프록시 로드 실패로 프로그램 종료")

def save_status(proxy, status):
    pass

def save_session_info(proxy, data):
    pass

def load_session_info(proxy):
    return {}

def is_valid_proxy(proxy):
    return True

def remove_proxy_from_list(proxy):
    pass

async def main():
    with open('proxy.txt', 'r') as f:
        all_proxies = f.read().splitlines()

    active_proxies = [proxy for proxy in all_proxies[:100] if is_valid_proxy(proxy)]  # 기본적으로 100개의 프록시를 동시에 실행
    tasks = {asyncio.create_task(render_profile_info(proxy)): proxy for proxy in active_proxies}

    while True:
        done, pending = await asyncio.wait(tasks.keys(), return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            failed_proxy = tasks[task]
            if task.result() is None:
                logger.info(f"실패한 프록시 제거 및 교체: {failed_proxy}")
                active_proxies.remove(failed_proxy)
                if all_proxies:
                    new_proxy = all_proxies.pop(0)
                    if is_valid_proxy(new_proxy):
                        active_proxies.append(new_proxy)
                        new_task = asyncio.create_task(render_profile_info(new_proxy))
                        tasks[new_task] = new_proxy
            tasks.pop(task)

        for proxy in set(active_proxies) - set(tasks.values()):
            new_task = asyncio.create_task(render_profile_info(proxy))
            tasks[new_task] = proxy

        await asyncio.sleep(3)  # 빠른 실패 방지를 위한 대기

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("사용자에 의해 프로그램 종료")
