import json
import os

def update_json(json_path, key, value):
    """
    Append or update a key:value pair in a JSON file safely.
    Creates the file if it doesn’t exist.
    """
    data = {}
    if os.path.exists(json_path):
        try:
            with open(json_path, "r") as f:
                data = json.load(f)
        except json.JSONDecodeError:
            data = {}

    data[key] = value

    # atomic write to avoid corruption
    tmp_path = f"{json_path}.tmp"
    with open(tmp_path, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp_path, json_path)
