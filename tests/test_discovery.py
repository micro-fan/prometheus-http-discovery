import json
import pathlib
import shutil

import pytest
from fan_tools.python import rel_path
from pytest_httpx import HTTPXMock

from app.main import discovery_collecting, get_discovery_config, pre_start


@pytest.fixture
def valid_config_path():
    yield rel_path('./cases/valid_config.yml')


@pytest.fixture
def init_config(valid_config_path):
    pre_start(valid_config_path)


@pytest.fixture
def clean_results(valid_config_path):
    yield
    shutil.rmtree('results', ignore_errors=True)


def test_get_discovery_config(valid_config_path):
    config = get_discovery_config(valid_config_path)

    assert config.output_dir == pathlib.Path('results')
    assert config.interval == 120
    assert len(config.discovery) == 3

    for disc_item in config.discovery:
        if disc_item.url == 'https://dev.url/api/v1/health/prometheus/service_discovery/':
            assert disc_item.default_labels == {'group': 'dev', 'some_label': 'some_value'}
        elif str(disc_item.url) == 'https://prod.url/api/v1/health/prometheus/service_discovery/':
            assert disc_item.default_labels == {'group': 'prod'}
        elif str(disc_item.url) == 'https://without.label/api/v1/health/prometheus/service_discovery/':
            assert disc_item.default_labels == {}
        else:
            assert False, f'Unknown url {disc_item.url}'


@pytest.mark.asyncio
@pytest.mark.usefixtures('init_config', 'clean_results')
async def test_discovery_collecting(httpx_mock: HTTPXMock):
    httpx_mock.add_response(
        url='https://dev.url/api/v1/health/prometheus/service_discovery/',
        json=[{
            'targets': ['dev.fashion:80'],
            'labels': {
                '__metrics_path__': '/api/v1/health/prometheus/',
                'service': 'django',
            }}],
    )
    httpx_mock.add_response(
        url='https://prod.url/api/v1/health/prometheus/service_discovery/',
        json=[{
            'targets': ['prod.fashion:80'],
            'labels': {
                '__metrics_path__': '/api/v1/health/prometheus/',
                'service': 'django',
            }}],
    )
    httpx_mock.add_response(
        url='https://without.label/api/v1/health/prometheus/service_discovery/',
        json=[{
            'targets': ['without.fashion:80'],
            'labels': {
                '__metrics_path__': '/api/v1/health/prometheus/',
                'service': 'django',
            }}],
    )

    await discovery_collecting()

    dev_disc = json.load(open('results/https_dev_url_api_v1_health_prometheus_service_discovery.json'))
    prod_disc = json.load(open('results/https_prod_url_api_v1_health_prometheus_service_discovery.json'))
    wl_disc = json.load(open('results/https_without_label_api_v1_health_prometheus_service_discovery.json'))

    assert len(dev_disc) == 1
    assert len(prod_disc) == 1
    assert len(wl_disc) == 1
    assert dev_disc[0]['labels'] == {
        '__metrics_path__': '/api/v1/health/prometheus/',
        'service': 'django',
        'group': 'dev',
        'some_label': 'some_value',
    }
    assert prod_disc[0]['labels'] == {
        '__metrics_path__': '/api/v1/health/prometheus/',
        'service': 'django',
        'group': 'prod',
    }
    assert wl_disc[0]['labels'] == {
        '__metrics_path__': '/api/v1/health/prometheus/',
        'service': 'django',
    }
