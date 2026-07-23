import json
import os
import sys

import requests
from dotenv import load_dotenv


def download_swagger():
    base_url = os.environ.get("LOOKERSDK_BASE_URL")
    
    if not base_url:
        # Try to load from .env in project root
        current_dir = os.path.dirname(os.path.abspath(__file__))
        env_path = os.path.join(current_dir, "..", "..", ".env")
        if os.path.exists(env_path):
            print(f"Loading environment from {env_path}")
            load_dotenv(env_path)
            base_url = os.environ.get("LOOKERSDK_BASE_URL")
                        
    if not base_url:
        print("Error: LOOKERSDK_BASE_URL environment variable not set.", file=sys.stderr)
        sys.exit(1)
    
    url = f"{base_url.rstrip('/')}/api/4.0/swagger.json"
    output_dir = os.path.dirname(os.path.abspath(__file__))
    output_path = os.path.join(output_dir, "swagger.json")
    
    print(f"Downloading swagger.json from {url} ...")
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        
        # Verify it's JSON
        try:
            swagger_data = response.json()
        except ValueError:
            print("Error: Response is not valid JSON.", file=sys.stderr)
            sys.exit(1)
            
        with open(output_path, "w") as f:
            json.dump(swagger_data, f, indent=2)
            
        print(f"Saved swagger.json to {output_path}")
    except requests.RequestException as e:
        print(f"Error downloading swagger.json: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    download_swagger()
