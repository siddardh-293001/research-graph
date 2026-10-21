"""Manual network probe; run explicitly with python -m src.ingestion.test_openalex."""
import requests
import json

def main():
    url = "https://api.openalex.org/works"
    
    params = {
        "search": "retrieval augmented generation",
        "per-page": 5,
    }
    
    response = requests.get(url, params=params, timeout=30)
    
    print("Status:", response.status_code)
    
    response.raise_for_status()
    
    data = response.json()
    
    print("Results:", len(data["results"]))
    
    # Print the complete data structure of the first paper
    print(json.dumps(data["results"][0], indent=2))


if __name__ == "__main__":
    main()
