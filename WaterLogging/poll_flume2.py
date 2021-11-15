import requests

# Under development. This replace tuya as the method for collection of water consumption data

url = "https://api.flumetech.com/users/user_id/devices/device_id/query"

headers = {
    'Content-Type': 'application/json',
    'Authorization': 'Bearer token'
}

payload = {
    "queries": [
            { "request_id": "abc", "bucket": "MON", "since_datetime": "2016-04-04 01:00:00", "group_multiplier": 3 },
            { "request_id": "xyz", "bucket": "DAY", "since_datetime": "2016-04-04 01:00:00", "until_datetime": "2016-04-07 01:00:00" }
        ]
}

response = requests.request("POST", url, json=payload, headers=headers)

print(response.text)
