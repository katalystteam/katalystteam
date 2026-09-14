import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

url = "https://www.cbre.com/properties"

response = requests.get(
    url,
    verify=False,
    timeout=30
)

print(response.status_code)
print(response.text[:500])
