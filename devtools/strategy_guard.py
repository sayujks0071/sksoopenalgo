#!/usr/bin/env python3
"""
Strategy Guard (The 'Ralph' Loop for OpenAlgo)
----------------------------------------------
This tool monitors a strategy file for changes and automatically runs:
1. Syntax Check (compile)
2. Import Check (dynamic import)
3. Runtime Check (generate_signal dry run)

Usage:
    python3 devtools/strategy_guard.py path/to/strategy.py
"""

import sys
import os
import time
import importlib.util
import traceback
import pandas as pd
import numpy as np
from datetime import datetime

# ANSI Colors
GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"


def print_status(status, message):
    color = GREEN if status == "PASS" else RED
    print(f"{color}[{status}] {message}{RESET}")


def check_syntax(file_path):
    try:
        with open(file_path, "r") as f:
            source = f.read()
        compile(source, file_path, "exec")
        return True, "Syntax OK"
    except SyntaxError as e:
        return False, f"Syntax Error: {e}"
    except Exception as e:
        return False, f"Error reading file: {e}"


def check_import_and_run(file_path):
    try:
        # Add project root to sys.path so internal imports work
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(file_path)))
        if project_root not in sys.path:
            sys.path.insert(0, project_root)

        spec = importlib.util.spec_from_file_location("strategy_module", file_path)
        if spec is None or spec.loader is None:
            return False, "Could not load spec"

        module = importlib.util.module_from_spec(spec)
        sys.modules["strategy_module"] = module

        # MOCKING: Inject dummy classes into the module's namespace BEFORE execution
        # This prevents the script from trying to import/initialize real trading_utils if they fail
        class DummyClient:
            def __init__(self, *args, **kwargs):
                pass

            def history(self, *args, **kwargs):
                return pd.DataFrame()

        class DummyPM:
            def __init__(self, *args, **kwargs):
                self.guardrails_enabled = False
                self.max_position_qty = 100
                self.default_qty = 1

            def has_position(self):
                return False

            def update_position(self, *args, **kwargs):
                pass

            def calculate_quantity_risk_based(self, *args, **kwargs):
                return 1

        if hasattr(module, "APIClient"):
            module.APIClient = DummyClient
        if hasattr(module, "PositionManager"):
            module.PositionManager = DummyPM

        # MOCKING: Inject into sys.modules to catch imports from the strategy
        # This is critical if the strategy imports 'trading_utils' or 'openalgo...'
        dummy_utils = type(sys)("trading_utils")
        dummy_utils.APIClient = DummyClient
        dummy_utils.PositionManager = DummyPM
        dummy_utils.is_market_open = lambda: True
        dummy_utils.normalize_symbol = lambda s: s

        sys.modules["trading_utils"] = dummy_utils
        sys.modules["utils.trading_utils"] = dummy_utils
        sys.modules["strategies.utils.trading_utils"] = dummy_utils
        sys.modules["openalgo.strategies.utils.trading_utils"] = dummy_utils

        # Determine exchange needs to work too if called
        os.environ["OPENALGO_APIKEY"] = "dummy_key"
        os.environ["OPENALGO_PORT"] = "5001"

        spec.loader.exec_module(module)

        # Check for generate_signal
        if hasattr(module, "generate_signal"):
            # Create dummy data
            dates = pd.date_range(end=datetime.now(), periods=50, freq="15min")
            df = pd.DataFrame(
                {
                    "open": np.random.rand(50) * 100,
                    "high": np.random.rand(50) * 100,
                    "low": np.random.rand(50) * 100,
                    "close": np.random.rand(50) * 100,
                    "volume": np.random.randint(100, 1000, 50),
                },
                index=dates,
            )

            try:
                signal = module.generate_signal(df)
                return True, f"Import OK & Dry Run OK (Signal: {signal})"
            except Exception as e:
                return False, f"Runtime Error in generate_signal: {e}"
        else:
            return True, "Import OK (No generate_signal found, skipping dry run)"

    except Exception as e:
        return False, f"Import Error: {e}\n{traceback.format_exc()}"


def monitor_file(file_path):
    print(f"{YELLOW}Starting Strategy Guard for: {file_path}{RESET}")
    print(f"{YELLOW}Press Ctrl+C to stop.{RESET}")

    last_mtime = 0

    while True:
        try:
            current_mtime = os.path.getmtime(file_path)
            if current_mtime > last_mtime:
                last_mtime = current_mtime
                os.system("cls" if os.name == "nt" else "clear")
                print(f"--- Check at {datetime.now().strftime('%H:%M:%S')} ---")

                # 1. Syntax Check
                ok, msg = check_syntax(file_path)
                if not ok:
                    print_status("FAIL", msg)
                    continue
                else:
                    print_status("PASS", "Syntax Check")

                # 2. Import & Runtime Check
                ok, msg = check_import_and_run(file_path)
                if not ok:
                    print_status("FAIL", msg)
                else:
                    print_status("PASS", msg)

            time.sleep(1)
        except KeyboardInterrupt:
            print("\nStopping Strategy Guard.")
            break
        except FileNotFoundError:
            print_status("FAIL", f"File found: {file_path}")
            time.sleep(2)
        except Exception as e:
            print_status("FAIL", f"Monitor Error: {e}")
            time.sleep(2)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 devtools/strategy_guard.py path/to/strategy.py")
        sys.exit(1)

    target_file = sys.argv[1]
    if not os.path.exists(target_file):
        print(f"Error: File not found: {target_file}")
        sys.exit(1)

    monitor_file(target_file)
