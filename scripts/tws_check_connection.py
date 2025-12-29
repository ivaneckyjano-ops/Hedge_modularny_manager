#!/usr/bin/env python3
"""Check TWS connection"""
import sys
sys.path.insert(0, '/home/narbon/Aplikácie/tws-webapp/venv/lib/python3.12/site-packages')
from ib_insync import IB
import random
import json

def main():
    if len(sys.argv) < 2:
        print(json.dumps({'connected': False, 'error': 'Usage: tws_check_connection.py PORT'}))
        sys.exit(1)
    
    port = int(sys.argv[1])
    
    try:
        ib = IB()
        ib.connect('127.0.0.1', port, clientId=random.randint(1000,9999), readonly=True, timeout=10)
        
        info = {
            'connected': True,
            'host': '127.0.0.1',
            'port': port,
            'accounts': ib.managedAccounts(),
            'serverVersion': ib.client.serverVersion()
        }
        
        ib.disconnect()
        print(json.dumps(info))
        
    except Exception as e:
        print(json.dumps({'connected': False, 'error': str(e)}))

if __name__ == '__main__':
    main()
