# prometheus-http-discovery

Prometheus service discovery using with HTTP API and `file_sd_config`.

## Install

```
docker pull prometheus-http-discovery
```

## Usage

```
docker run -e DISCOVERY_CONFIG=/discovery.yml -v /path/to/discovery.yml:/discovery.yml -v /path/to/discvery/results:/results prometheus-http-discovery
```

`discovery.yml` file example:

```yaml
output_dir: results
interval: 30
configs:
  - job_name: my_services
    metrics_path: /metrics/service_discovery/path/
    static_configs:
      - targets:
        - 'http://server1.com'
        - 'https://server2.com'
        labels:
          group: 'some_group_name'
      - targets:
        - 'http://server3.com'
        - 'https://server4.com'
  
  - job_name: another_services
    targets:
      - 'http://another_server1.com/metrics/service_discovery/path/'
      - 'https://another_server2.com/metrics/service_discovery/path/'
```

## HTTP API format

HTTP API response should be followed prometheus `file_sd_config` format like below:

```json
[
  {
    "targets": [
      "my_service:80",
      "my_service_2:443"
    ],
    "labels": {
      "service": "web",
      "__metrics_path__": "/metrics/path/"
    }
  },
  {
    "targets": [
      "my_service_3:8000"
    ],
    "labels": {
      "service": "web_service_3"
    }
  }
]
```

## Prometheus settings

The part of your `prometheus.yml` is probably as follows.

```yaml
scrape_configs:
  - job_name: 'http_discpvery'
    file_sd_configs:
    - files:
      - '/path/to/discovery/folder/*.json'
```

## Metrics

`/metrics/` endpoint return metrics:

```
up 1
discovery_count 3
discovery_error_count 2
discovery_collecting_count 2
discovery_duration_avg 1.16
```
