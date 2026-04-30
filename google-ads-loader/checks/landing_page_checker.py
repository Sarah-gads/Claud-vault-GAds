import logging
from pathlib import Path

import requests
import yaml

logger = logging.getLogger(__name__)

_TIMEOUT = 10
_SLOW_THRESHOLD_S = 4.0


def check_all_clients(clients_dir: str) -> list[dict]:
    issues = []
    clients_path = Path(clients_dir)

    for config_file in clients_path.glob("*.yaml"):
        if config_file.name == "client_template.yaml":
            continue
        try:
            with config_file.open(encoding="utf-8") as f:
                config = yaml.safe_load(f)
        except Exception as e:
            logger.error(f"Failed to parse {config_file}: {e}")
            continue

        base_url = config.get("landing_page", {}).get("base_url", "")
        path = config.get("landing_page", {}).get("path", "")
        if not base_url:
            continue

        url = base_url.rstrip("/") + path
        client_name = config.get("client", {}).get("name", config_file.stem)
        issue = _check_url(url, client_name)
        if issue:
            issues.append(issue)

    return issues


def _check_url(url: str, client_name: str) -> dict | None:
    try:
        resp = requests.get(url, timeout=_TIMEOUT, allow_redirects=True)
        elapsed = resp.elapsed.total_seconds()

        if resp.status_code >= 400:
            logger.warning(
                f"Landing page error [{resp.status_code}] for {client_name}: {url}"
            )
            return {
                "type": "landing_page_error",
                "client_name": client_name,
                "url": url,
                "status_code": resp.status_code,
                "elapsed_s": round(elapsed, 2),
                "details": (
                    f"Landing page returned HTTP {resp.status_code} "
                    f"for '{client_name}' — {url}"
                ),
            }

        if elapsed > _SLOW_THRESHOLD_S:
            logger.warning(
                f"Slow landing page ({elapsed:.1f}s) for {client_name}: {url}"
            )
            return {
                "type": "landing_page_slow",
                "client_name": client_name,
                "url": url,
                "status_code": resp.status_code,
                "elapsed_s": round(elapsed, 2),
                "details": (
                    f"Landing page loaded in {elapsed:.1f}s (threshold {_SLOW_THRESHOLD_S}s) "
                    f"for '{client_name}' — {url}"
                ),
            }

        logger.debug(f"Landing page OK [{resp.status_code}] {elapsed:.1f}s — {url}")
        return None

    except requests.Timeout:
        logger.warning(f"Landing page timed out after {_TIMEOUT}s for {client_name}: {url}")
        return {
            "type": "landing_page_timeout",
            "client_name": client_name,
            "url": url,
            "status_code": 0,
            "elapsed_s": _TIMEOUT,
            "details": (
                f"Landing page timed out ({_TIMEOUT}s) for '{client_name}' — {url}"
            ),
        }
    except requests.RequestException as e:
        logger.error(f"Landing page request failed for {client_name}: {e}")
        return {
            "type": "landing_page_error",
            "client_name": client_name,
            "url": url,
            "status_code": 0,
            "elapsed_s": 0,
            "details": f"Landing page unreachable for '{client_name}' — {url}: {e}",
        }
