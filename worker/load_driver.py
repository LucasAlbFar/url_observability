import asyncio

import httpx

URLS = [
    "http://app:8002/load/io-bound",
    "http://app:8002/load/cpu-bound",
    "http://app:8002/load/memory-spike",
    "http://app:8002/load/stress/1",
]


async def call_endpoint(url):
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            response = await client.get(url)
            print(f"{url}: {response.status_code}")
    except Exception as e:
        print(f"{url}: {e}")


async def main(cycles: int = None):
    count = 0
    while cycles is None or count < cycles:
        tasks = [call_endpoint(url) for url in URLS]
        await asyncio.gather(*tasks)
        await asyncio.sleep(5)
        count += 1


if __name__ == "__main__":
    asyncio.run(main())  # pragma: no cover
