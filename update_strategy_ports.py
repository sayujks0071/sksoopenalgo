import json
import os

CONFIG_FILE = "openalgo/strategies/strategy_configs.json"


def update_ports():
    if not os.path.exists(CONFIG_FILE):
        print(f"Config file not found: {CONFIG_FILE}")
        return

    with open(CONFIG_FILE, "r") as f:
        configs = json.load(f)

    updated_count = 0
    for strategy_id, config in configs.items():
        args = config.get("script_args", [])
        new_args = []
        changed = False

        # simple list replacement
        if isinstance(args, list):
            for i, arg in enumerate(args):
                if arg == "--port" and i + 1 < len(args) and str(args[i + 1]) == "5000":
                    new_args.append(arg)
                    new_args.append("5002")
                    changed = True
                    # skip next
                elif i > 0 and args[i - 1] == "--port" and str(arg) == "5000":
                    continue  # already handled
                else:
                    new_args.append(arg)

            if changed:
                config["script_args"] = new_args
                updated_count += 1

        # string replacement (legacy)
        elif isinstance(args, str):
            if "--port 5000" in args:
                config["script_args"] = args.replace("--port 5000", "--port 5002")
                updated_count += 1

    if updated_count > 0:
        with open(CONFIG_FILE, "w") as f:
            json.dump(configs, f, indent=2)
        print(f"Updated ports for {updated_count} strategies.")
    else:
        print("No strategies needed port update.")


if __name__ == "__main__":
    update_ports()
