import asyncio, json
from fastapi import Request
from whatsapp_handler import whatsapp_webhook

async def receive():
    payload = {'object': 'whatsapp_business_account', 'entry': [{'id': '1386278206561216', 'changes': [{'value': {'messaging_product': 'whatsapp', 'metadata': {'display_phone_number': '15551368573', 'phone_number_id': '1038171312721591'}, 'contacts': [{'profile': {'name': 'tester'}, 'wa_id': '923202042302', 'user_id': 'PK.974452431931151'}], 'messages': [{'from': '923202042302', 'from_user_id': 'PK.974452431931151', 'id': '1', 'timestamp': '1', 'text': {'body': 'Hey'}, 'type': 'text'}]}, 'field': 'messages'}]}]}
    return {'type': 'http.request', 'body': json.dumps(payload).encode()}

async def main():
    scope={'type':'http', 'method':'POST', 'headers':[]}
    r = Request(scope, receive)
    try:
        resp = await whatsapp_webhook(r)
        print("Final Status:", resp.status_code)
        print("Final Body:", resp.body)
    except Exception as e:
        import traceback
        traceback.print_exc()

asyncio.run(main())
