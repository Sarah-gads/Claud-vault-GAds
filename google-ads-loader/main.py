"""
MSP Campaign Loader — CLI entry point
Usage:
  python main.py --client client_configs/acme_it.json
  python main.py --all                    # runs every .json in client_configs/
  python main.py --client x.json --dry-run
"""
import argparse
import json
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from google.ads.googleads.client import GoogleAdsClient

from loader.campaign_builder import CampaignBuilder, ValidationFailed
from loader.clickup_client import ClickUpClient
from loader.discord_notifier import DiscordNotifier
from loader.validator import format_errors

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger(__name__)

_REQUIRED_ENV = [
    "GOOGLE_ADS_DEVELOPER_TOKEN",
    "GOOGLE_ADS_CLIENT_ID",
    "GOOGLE_ADS_CLIENT_SECRET",
    "GOOGLE_ADS_REFRESH_TOKEN",
    "GOOGLE_ADS_LOGIN_CUSTOMER_ID",
    "CLICKUP_API_TOKEN",
    "CLICKUP_LIST_ID",
    "CLICKUP_ASSIGNEE_ID",
    "DISCORD_WEBHOOK_URL",
]

_HERE          = Path(__file__).parent
_CONFIGS_DIR   = _HERE / "client_configs"
_ASSETS_DIR    = _HERE / "client_configs" / "assets"
_REGISTRY_FILE = _HERE / "campaign_registry.json"


def _load_env() -> dict:
    missing = [k for k in _REQUIRED_ENV if not os.environ.get(k)]
    if missing:
        logger.error(f"Missing env vars: {', '.join(missing)}")
        sys.exit(1)
    return {k: os.environ[k] for k in _REQUIRED_ENV}


def _load_google_client(env: dict) -> GoogleAdsClient:
    return GoogleAdsClient.load_from_dict({
        "developer_token":   env["GOOGLE_ADS_DEVELOPER_TOKEN"],
        "client_id":         env["GOOGLE_ADS_CLIENT_ID"],
        "client_secret":     env["GOOGLE_ADS_CLIENT_SECRET"],
        "refresh_token":     env["GOOGLE_ADS_REFRESH_TOKEN"],
        "login_customer_id": env["GOOGLE_ADS_LOGIN_CUSTOMER_ID"],
        "use_proto_plus":    True,
    })


def _load_config(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        config = json.load(f)
    # Strip meta-only keys that start with _
    for key in list(config.keys()):
        if key.startswith("_"):
            del config[key]
    return config


def _update_registry(result: dict) -> None:
    registry = {"campaigns": []}
    if _REGISTRY_FILE.exists():
        try:
            registry = json.loads(_REGISTRY_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    registry["campaigns"].append({
        k: v for k, v in result.items()
        if k not in ("summary", "summary_markdown")
    })
    _REGISTRY_FILE.write_text(json.dumps(registry, indent=2), encoding="utf-8")


def _collect_configs(args) -> list[tuple[Path, dict]]:
    configs = []
    if args.client:
        path = Path(args.client)
        configs.append((path, _load_config(path)))
    else:
        for json_file in sorted(_CONFIGS_DIR.glob("*.json")):
            if json_file.name.startswith("client_template"):
                continue
            configs.append((json_file, _load_config(json_file)))
    return configs


def main() -> None:
    parser = argparse.ArgumentParser(description="MSP Campaign Loader")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--client", metavar="PATH", help="Path to a single client JSON config")
    group.add_argument("--all", dest="run_all", action="store_true", help="Process all configs in client_configs/")
    parser.add_argument("--dry-run", action="store_true", help="Validate only — do not call Google Ads API")
    args = parser.parse_args()

    if not args.client and not args.run_all:
        parser.print_help()
        sys.exit(1)

    env     = _load_env()
    configs = _collect_configs(args)

    if not configs:
        logger.error("No config files found.")
        sys.exit(1)

    logger.info(f"Loaded {len(configs)} config file(s)")

    if args.dry_run:
        from loader.validator import ConfigValidator
        all_ok = True
        for path, config in configs:
            errs = ConfigValidator().validate(config, _ASSETS_DIR)
            if errs:
                print(f"\n✗ {path.name}:{format_errors(errs)}")
                all_ok = False
            else:
                print(f"✓ {path.name} — config valid")
        sys.exit(0 if all_ok else 1)

    google_client = _load_google_client(env)
    builder = CampaignBuilder(google_client, str(_HERE / "templates"), str(_ASSETS_DIR))
    clickup = ClickUpClient(env["CLICKUP_API_TOKEN"], env["CLICKUP_LIST_ID"], env["CLICKUP_ASSIGNEE_ID"])
    discord = DiscordNotifier(env["DISCORD_WEBHOOK_URL"])

    successes, failures = 0, 0

    for path, config in configs:
        client_name = config.get("client", {}).get("name", path.stem)
        logger.info(f"{'─'*60}")
        logger.info(f"Processing: {client_name}  ({path.name})")

        result = {}
        try:
            result = builder.build(config)
            _update_registry(result)

            # ClickUp — use markdown summary as task description
            cu_list_id    = config.get("notifications", {}).get("clickup_list_id")    or env["CLICKUP_LIST_ID"]
            cu_assignee   = config.get("notifications", {}).get("clickup_assignee_id") or env["CLICKUP_ASSIGNEE_ID"]
            client_clickup = ClickUpClient(env["CLICKUP_API_TOKEN"], cu_list_id, cu_assignee)

            client_clickup.create_campaign_review_task_from_summary(
                campaign_name=result["campaign_name"],
                summary_markdown=result["summary_markdown"],
                client_name=result["client_name"],
            )

            # Discord
            if config.get("notifications", {}).get("discord_enabled", True):
                discord.campaign_created(result, config)

            successes += 1
            logger.info(f"SUCCESS: {client_name}")

        except ValidationFailed as vf:
            failures += 1
            logger.error(f"VALIDATION FAILED — {client_name}:{vf}")

        except Exception as e:
            failures += 1
            logger.error(f"FAILED — {client_name}: {e}")
            if config.get("notifications", {}).get("discord_enabled", True):
                discord.campaign_error(
                    result or {"client_name": client_name, "campaign_name": "N/A"},
                    str(e),
                )

    logger.info(f"{'─'*60}")
    logger.info(f"Done — {successes} created, {failures} failed.")
    if failures:
        sys.exit(1)


if __name__ == "__main__":
    main()
