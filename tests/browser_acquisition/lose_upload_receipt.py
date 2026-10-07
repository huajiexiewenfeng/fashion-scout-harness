"""Test-only exit after a real binary API response, before client receipt fsync."""
import os
from fashion_scout.client import Connection,main

original=Connection.upload
def lose_receipt(self,*args,**kwargs):
    original(self,*args,**kwargs)
    os._exit(73)

if __name__=='__main__':
    Connection.upload=lose_receipt
    raise SystemExit(main())
