"""Run interactively or using HAOS /data/options.json; never log credentials."""
import argparse
import getpass
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .client import NetworkError, StatusClient
from .errors import MQTTError
from .protocol import (
    AccountRemovedError, AuthenticationError, PanelOfflineError, ProtocolError,
    ServerRejectedError, SessionReplacedError,
)


def run(options):
    samples = options.get("samples", 1)
    interval = options.get("interval", 10)
    if type(samples) is not int or not 1 <= samples <= 300:
        raise ValueError("samples must be an integer from 1 to 300")
    if type(interval) is not int or not 5 <= interval <= 300:
        raise ValueError("interval must be an integer from 5 to 300")
    if type(options.get("allow_plaintext", False)) is not bool:
        raise ValueError("allow_plaintext must be a boolean")
    include_accessories = options.get("include_accessories", False)
    if type(include_accessories) is not bool:
        raise ValueError("include_accessories must be a boolean")
    event_diagnostics = options.get("event_diagnostics",False)
    if type(event_diagnostics) is not bool:
        raise ValueError("event_diagnostics must be a boolean")
    if event_diagnostics:
        logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
    zone = ZoneInfo(options.get("timezone", "Europe/Athens"))
    client = StatusClient(options.get("device_id", ""), options.get("username", ""),
                          options.get("password", ""),
                          allow_plaintext=options.get("allow_plaintext", False),
                          event_diagnostics=event_diagnostics)
    print("Experimental H4 status probe: login and status queries only; no arm/disarm commands.", file=sys.stderr, flush=True)
    previous_mode_code = None
    try:
        client.connect()
        for i in range(samples):
            status = client.status(datetime.now(zone))
            output = status.as_dict()
            output["accessory_count"] = len(status.accessories)
            output["mode_changed"] = None if previous_mode_code is None else status.mode_code != previous_mode_code
            previous_mode_code = status.mode_code
            if not include_accessories:
                del output["accessories"]
            output["observed_at"] = datetime.now(timezone.utc).isoformat()
            output["sample"] = i + 1
            print(json.dumps(output), flush=True)
            if i + 1 < samples:
                client.wait(interval)
    finally:
        client.close()
    print(f"Probe completed normally after {samples} samples.", file=sys.stderr, flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Experimental status-only Chuango H4 probe")
    parser.add_argument("--options", type=Path, help="Private JSON options file (HAOS uses /data/options.json)")
    parser.add_argument("--allow-plaintext", action="store_true", help="Accept the app's unencrypted TCP login transport")
    parser.add_argument("--samples", type=int, default=1)
    parser.add_argument("--interval", type=int, default=10)
    parser.add_argument("--timezone", default="Europe/Athens")
    parser.add_argument("--include-accessories", action="store_true", help="Include raw accessory records in logs")
    parser.add_argument("--event-diagnostics", action="store_true", help="Log safe incoming IDs between polls; no event-driven state updates")
    args = parser.parse_args(argv)
    try:
        if args.options:
            options = json.loads(args.options.read_text())
            if not isinstance(options, dict):
                raise ValueError("Options must be a JSON object")
        else:
            if not args.allow_plaintext:
                parser.error("The app uses unencrypted TCP. Read README.md and use --allow-plaintext to opt in.")
            options = {"device_id": input("Panel device ID: "), "username": input("App username: "),
                       "password": getpass.getpass("App password: "),
                       "allow_plaintext": True, "samples": args.samples,
                       "interval": args.interval, "timezone": args.timezone,
                       "include_accessories": args.include_accessories,
                       "event_diagnostics": args.event_diagnostics}
        run_mode = options.get("run_mode","probe")
        if run_mode == "mqtt":
            from .bridge import run_bridge
            logging.basicConfig(level=logging.INFO,format="%(asctime)s %(levelname)s %(message)s")
            run_bridge(options)
        elif run_mode == "probe":
            run(options)
        else:
            raise ValueError("Unsupported run mode")
        return 0
    except SessionReplacedError as error:
        print(f"Session ended: {error}. Another app login may have replaced this session. "
              "Probe stopped; no automatic login retries.", file=sys.stderr)
    except AccountRemovedError as error:
        print(f"Account notification: {error}. Probe stopped; no automatic login retries.", file=sys.stderr)
    except AuthenticationError as error:
        print(f"Authentication failed: {error}. No automatic login retries.", file=sys.stderr)
    except PanelOfflineError:
        print("Panel offline according to server. No status asserted.", file=sys.stderr)
    except NetworkError as error:
        print(f"Network failure: {error}. No new status confirmed; "
              "probe stopped without automatic login retries.", file=sys.stderr)
    except MQTTError as error:
        print(f"MQTT failure: {error}. Check that Mosquitto is running and MQTT is configured.",file=sys.stderr)
    except ServerRejectedError as error:
        logging.error("Alarm server rejection: %s. Bridge/probe stopped; no status asserted.", error)
    except ProtocolError as error:
        print(f"Protocol compatibility check failed: {error}. No status asserted.", file=sys.stderr)
    except (OSError, TimeoutError):
        print("Network or options-file access failed. Check connectivity and file access; no status asserted.", file=sys.stderr)
    except (ValueError, TypeError, ZoneInfoNotFoundError):
        print("Invalid options. Check required fields, limits, timezone and plaintext opt-in.", file=sys.stderr)
    except (KeyboardInterrupt, EOFError):
        print("Probe stopped.", file=sys.stderr)
        return 130
    return 1


if __name__ == "__main__":
    sys.exit(main())
