import json

with open('dump_next_data.json', encoding='utf-8') as f:
    d = json.load(f)
    
data = d['props']['pageProps']['data']

result = {
    "allAddresses": data.get("allAddresses"),
    "allPhonesList": data.get("allPhonesList"),
    "contactMap": data.get("contactMap"),
    "emails": data.get("emails"),
    "infoEmpresa": data.get("infoEmpresa"),
    "services": data.get("services"),
    "slogan": data.get("slogan")
}

with open("printed.json", "w", encoding="utf-8") as out:
    json.dump(result, out, indent=2, ensure_ascii=False)
