from typing import Annotated,Literal
from pydantic import Field,model_validator
from fastapi import Request
from fashion_scout.domain.models import DTO
from fashion_scout.maintenance.jobs import Jobs
from fashion_scout.maintenance.storage import Storage
from .models import Operation

ProductId=Annotated[str,Field(min_length=1,max_length=128,pattern=r'^[A-Za-z0-9_-]+$')]


class VerifyOptions(DTO):
    scope:Literal['all','selected']
    product_ids:list[ProductId]|None=None

    @model_validator(mode='after')
    def selection(self):
        if self.scope=='all' and 'product_ids' in self.model_fields_set:raise ValueError('all cannot select IDs')
        if self.scope=='selected' and (not self.product_ids or len(self.product_ids)>1000 or len(set(self.product_ids))!=len(self.product_ids)):raise ValueError('selected requires unique IDs')
        return self


class VerifyRequest(Operation,VerifyOptions):pass


class BackupOptions(DTO):
    destination_id:Literal['local']


class BackupRequest(Operation,BackupOptions):pass


class StoragePatch(DTO):
    expected_revision:int=Field(ge=0)
    media_root:str=Field(min_length=1,max_length=1024)


def install_maintenance(app,paths,result):
    jobs,storage=Jobs(paths),Storage(paths)

    @app.get('/v1/maintenance')
    def recent(request:Request):return result(request,{'items':jobs.recent(),'capabilities':['verify','backup-local','offline-restore']})

    @app.post('/v1/maintenance/verify')
    def verify(payload:VerifyRequest,request:Request):
        options=payload.model_dump(exclude={'request_key'},exclude_none=True)
        jid,reused=jobs.create('verify',payload.request_key,options)
        return result(request,{'maintenance':jobs.get(jid),'reused':reused},200 if reused else 202)

    @app.post('/v1/maintenance/backup')
    def backup(payload:BackupRequest,request:Request):
        jid,reused=jobs.create('backup',payload.request_key,{'destination_id':payload.destination_id})
        return result(request,{'maintenance':jobs.get(jid),'reused':reused},200 if reused else 202)

    @app.get('/v1/maintenance/{jid}')
    def get(jid:str,request:Request):return result(request,{'maintenance':jobs.get(jid)})

    @app.get('/v1/settings/storage')
    def get_storage(request:Request):return result(request,{'storage':storage.get()})

    @app.patch('/v1/settings/storage')
    def patch_storage(payload:StoragePatch,request:Request):return result(request,{'storage':storage.patch(payload.expected_revision,payload.media_root)})
