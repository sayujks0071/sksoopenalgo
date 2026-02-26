import json
import os

CONFIG_FILE = "openalgo/strategies/strategy_configs.json"


def reset_strategies():
    if not os.path.exists(CONFIG_FILE):
        print(f"Config file not found: {CONFIG_FILE}")
        return

    with open(CONFIG_FILE, "r") as f:
        configs = json.load(f)

    for strategy_id, config in configs.items():
        if config.get("is_running", False):
            print(f"Resetting {strategy_id}...")
            config["is_running"] = False
            config["pid"] = None
            config["last_stopped"] = "2026-02-10T10:00:00"  # Dummy stop time

    with open(CONFIG_FILE, "w") as f:
        json.dump(configs, f, indent=2)

    print("All strategies reset.")


if __name__ == "__main__":
    reset_strategies()
