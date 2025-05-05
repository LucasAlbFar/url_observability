import asyncio
import time

from fastapi import APIRouter

router = APIRouter()


@router.get("/io-bound")
async def simulate_io_bound():
    await asyncio.sleep(2)
    return {"message": "I/O-bound task completed"}


@router.get("/cpu-bound")
def simulate_cpu_bound():
    def cpu_heavy_task():
        x = 0
        for _ in range(10_000_000):
            x += 1
        return x

    result = cpu_heavy_task()
    return {"message": "CPU-bound task completed", "result": result}


@router.get("/memory-spike")
def simulate_memory_spike():
    big_list = [0] * 10_000_000  # ~80MB
    return {"message": "Memory spike simulated", "length": len(big_list)}


@router.get("/stress/{seconds}")
def stress(seconds: int):
    end = time.time() + seconds
    while time.time() < end:
        pass
    return {"message": f"CPU stressed for {seconds} seconds"}
