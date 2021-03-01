import asyncio
import json
import logging
import os
import pathlib
import shutil
import statistics
import time
from typing import Any, Dict, List, Optional

import httpx
import pydantic
import uvicorn
import yaml
from fan_tools.container_utils import BaseMetricsView, MetricStorage
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Route

logger = logging.getLogger(__name__)
loop = asyncio.get_event_loop()
metric_storage = MetricStorage()

COLLECTOR_ERROR_COUNT = 0
TEMP_DIR = pathlib.Path("/tmp/")
METRIC_COLLECTING_COUNT = "discovery_collecting_count"
METRIC_DURATION_AVG = "discovery_duration_avg"
CONFIG = None


class ConfigDiscoveryItem(pydantic.BaseModel):
    url: pydantic.HttpUrl
    file: Optional[str] = None

    @pydantic.root_validator
    def set_file(cls, values):
        url = values.get("url")
        if not values.get("file"):
            values["file"] = (
                url.replace("://", "_").replace(".", "_").replace("/", "_").strip("_")
            )
            values["file"] = f'{values["file"]}.json'
        return values


class Config(pydantic.BaseModel):
    interval: int = 60
    output_dir: pathlib.Path = pathlib.Path("/results")
    discovery: Optional[List[ConfigDiscoveryItem]] = None

    @pydantic.validator("output_dir")
    def output_dir_validator(cls, v):
        if not v:
            raise ValueError("Output dir not set.")
        if not str(v).startswith("/"):
            v = pathlib.Path(f"/{v}")
        return v


class DiscoveryItem(pydantic.BaseModel):
    targets: List[str]
    labels: Dict[str, Any]


def get_discovery_config() -> Config:
    discovery_config = os.environ.get("DISCOVERY_CONFIG")
    if not discovery_config:
        raise ValueError("DISCOVERY_CONFIG file not found.")
    config = {
        "interval": os.environ.get("INTERVAL", 60),
        "output_dir": pathlib.Path(os.environ.get("OUTPUT_DIR", "/results")),
        "discovery": [],
    }
    config_file = pathlib.Path(discovery_config)
    with open(config_file) as config_file:
        data = yaml.load(config_file, Loader=yaml.FullLoader)
        discovery_urls = []
        configs = data.pop("configs", [])
        for config in configs:
            path = config.get("metrics_path")
            targets = config.get("targets", [])
            if path:
                targets = [f"{target}{path}" for target in targets]
            discovery_urls.extend(targets)
        data["discovery"] = [{"url": url} for url in set(discovery_urls)]
        if not data["discovery"]:
            raise ValueError("No discovery items.")
        config.update(**data)
    try:
        return pydantic.parse_obj_as(Config, config)
    except pydantic.error_wrappers.ValidationError:
        raise ValueError("Invalid config.")


async def fetch_discovery(url: str) -> List[DiscoveryItem]:
    async with httpx.AsyncClient() as client:
        response = await client.get(url)
        response.raise_for_status()
        try:
            return pydantic.parse_obj_as(List[DiscoveryItem], response.json())
        except json.decoder.JSONDecodeError:
            raise ValueError("Not json response.")
        except pydantic.error_wrappers.ValidationError:
            raise ValueError("Discovery response not valid. Check response schema.")


async def update_discovery_file(
    path: pathlib.Path, discovery_data: List[DiscoveryItem]
):
    data = [item.dict() for item in discovery_data]
    with open(path, "w+") as f:
        f.write(json.dumps(data))


async def metrics(request: Request) -> List[str]:
    out = []
    metrics = metric_storage.get_metrics()
    out.append(f"discovery_count {len(CONFIG.discovery)}")
    out.append(f"discovery_error_count {COLLECTOR_ERROR_COUNT}")
    out.append(f"{METRIC_COLLECTING_COUNT} {metrics.get(METRIC_COLLECTING_COUNT, 0)}")
    if values := metrics.get(METRIC_DURATION_AVG, []):
        value = statistics.mean(values[-5:])
        value = round(value, 2)
    else:
        value = 0
    out.append(f"{METRIC_DURATION_AVG} {value}")
    return out


async def copy_to_output():
    files_list = TEMP_DIR.glob("**/*")
    for file in files_list:
        shutil.move(file, pathlib.Path(CONFIG.output_dir, file.name))
    available_files = [item.file for item in CONFIG.discovery]
    for file in pathlib.Path(CONFIG.output_dir).glob("**/*"):
        if file.name not in available_files:
            file.unlink()


async def discovery_collecting():
    global COLLECTOR_ERROR_COUNT
    COLLECTOR_ERROR_COUNT = 0
    start = time.time()
    metric_storage.increment(METRIC_COLLECTING_COUNT)
    for discovery_item in CONFIG.discovery:
        try:
            discovery_items = await fetch_discovery(discovery_item.url)
            temp_path = pathlib.Path(f"{TEMP_DIR}/{discovery_item.file}")
            await update_discovery_file(
                temp_path,
                discovery_items,
            )
        except Exception as exc:
            COLLECTOR_ERROR_COUNT += 1
            logger.error(f"Collect error: {str(exc)}.")
    metric_storage.push(METRIC_DURATION_AVG, time.time() - start)
    logger.info("Collecting finished.")
    await copy_to_output()


async def metrics_view(request):
    data = await metrics(request)
    return Response("\n".join(data))


async def discovery_collecting_task():
    while True:
        await discovery_collecting()
        await asyncio.sleep(CONFIG.interval)


async def startup_event():
    loop = asyncio.get_event_loop()
    loop.create_task(discovery_collecting_task())


class PrometheusView(BaseMetricsView):
    async def get_default(self):
        return ["up 1"]


def create_folders():
    dirs = [
        pathlib.Path(TEMP_DIR),
        pathlib.Path(CONFIG.output_dir),
    ]
    for dir in dirs:
        dir.mkdir(parents=True, exist_ok=True)


app = Starlette(
    debug=True,
    routes=[
        Route("/metrics/", endpoint=PrometheusView(metrics)),
    ],
    on_startup=[startup_event],
)

if __name__ == "__main__":
    CONFIG = get_discovery_config()
    create_folders()
    uvicorn.run(app, host="0.0.0.0")
