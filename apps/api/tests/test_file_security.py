from io import BytesIO
from zipfile import ZipFile, ZIP_DEFLATED, ZipInfo
import stat

import pytest
from PIL import Image
from sqlalchemy.orm import Session

from lifepilot.config import settings
from lifepilot.db import engine
from lifepilot.models import Attachment, Person, EventPhoto
from lifepilot.approval_policy import queue
from lifepilot import file_security, document_routes


def image_bytes(fmt="PNG", animated=False):
    image=Image.new("RGB",(20,10),"green")
    output=BytesIO()
    if animated:
        image.save(output,format=fmt,save_all=True,append_images=[Image.new("RGB",image.size,"red")],duration=100)
    else:
        exif=Image.Exif()
        exif[270]="Private description"
        image.save(output,format=fmt,exif=exif)
    return output.getvalue()


def package(extra=(), root="word/document.xml"):
    data=BytesIO()
    with ZipFile(data,"w",ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml","<Types/>")
        archive.writestr(root,"<document/>")
        for name,value in extra:
            archive.writestr(name,value)
    return data.getvalue()


def upload(client,auth,mid,name,body):
    return client.post("/api/attachments",headers=auth,data={"resource_type":"memory","resource_id":mid},files={"file":(name,body)})


def test_attachment_formats_and_container_limits(client,auth,tmp_path,monkeypatch):
    monkeypatch.setattr(settings,"data_dir",str(tmp_path))
    mid=client.post("/api/memories",headers=auth,json={"title":"Dateiprüfung","content":"Test"}).json()["id"]
    link=ZipInfo("word/link")
    link.create_system=3
    link.external_attr=(stat.S_IFLNK|0o777)<<16
    for filename,contents in [
        ("fake.jpg",image_bytes()),
        ("fake.txt",b"\xff\xfe"),
        ("binary.txt",b"abc\x01def"),
        ("wrong.docx",package(root="xl/workbook.xml")),
        ("traversal.docx",package([("../outside","x")])),
        ("link.docx",package([(link,"target")])),
        ("duplicate.docx",package([("WORD/DOCUMENT.XML","duplicate")])),
        ("macro.docx",package([("word/vbaProject.bin","macro")])),
        ("ratio.docx",package([("word/large.xml",b"x"*(2*1024*1024))])),
        ("animated.png",image_bytes(animated=True)),
    ]:
        response=upload(client,auth,mid,filename,contents)
        assert response.status_code==415,(filename,response.text)
    assert client.get("/api/attachments",headers=auth,params={"resource_type":"memory","resource_id":mid}).json()==[]
    valid=upload(client,auth,mid,"picture.png",image_bytes())
    assert valid.status_code==201,valid.text
    download=client.get("/api/attachments/"+valid.json()["id"]+"/download",headers=auth)
    assert download.headers["content-security-policy"]=="sandbox; default-src 'none'"
    assert download.content==image_bytes()


def test_upload_limit_before_parsing_and_streaming(client,auth,monkeypatch):
    monkeypatch.setattr(file_security,"MAX_ATTACHMENT_BYTES",1024)
    monkeypatch.setattr(file_security,"MAX_MULTIPART_OVERHEAD",128)
    result=client.post("/api/attachments",headers={**auth,"Content-Length":"99999999","Content-Type":"multipart/form-data; boundary=test"},content=b"x")
    assert result.status_code==413
    # No content-length: the ASGI body itself must also be limited.
    def chunks():
        for _ in range(3):
            yield b"x"*512
    result=client.post("/api/attachments",headers={**auth,"Content-Type":"multipart/form-data; boundary=test"},content=chunks())
    assert result.status_code==413
    # Slot must have been released after rejection.
    assert client.post("/api/attachments",headers=auth,content=b"").status_code==422


def test_tampered_storage_key_and_symlink_do_not_escape(client,auth,tmp_path,monkeypatch):
    root=tmp_path/"data"
    monkeypatch.setattr(settings,"data_dir",str(root))
    outside=tmp_path/"outside.txt"
    outside.write_text("private")
    mid=client.post("/api/memories",headers=auth,json={"title":"Pfadprüfung","content":"Test"}).json()["id"]
    aid=upload(client,auth,mid,"safe.txt",b"safe").json()["id"]
    with Session(engine) as db:
        row=db.get(Attachment,aid)
        owner,key=row.owner_id,row.storage_key
        row.storage_key=str(outside)
        db.commit()
    for method,path in [("GET","/api/attachments/"+aid+"/download"),("POST","/api/documents/"+aid+"/extract"),("DELETE","/api/attachments/"+aid)]:
        assert client.request(method,path,headers=auth,**({"json":{}} if method=="POST" else {})).status_code==409
    assert outside.read_text()=="private"
    with Session(engine) as db:
        db.get(Attachment,aid).storage_key=key
        db.commit()
    original=root/"attachments"/owner/key
    original.unlink()
    original.symlink_to(outside)
    assert client.get("/api/attachments/"+aid+"/download",headers=auth).status_code==409
    assert client.post("/api/documents/"+aid+"/extract",headers=auth,json={}).status_code==409
    assert client.delete("/api/attachments/"+aid,headers=auth).status_code==409
    assert outside.read_text()=="private"
    original.unlink()
    original.write_bytes(b"safe")
    assert client.delete("/api/attachments/"+aid,headers=auth).status_code==204


def test_photos_strip_metadata_and_reject_unsafe_paths(client,auth,tmp_path,monkeypatch):
    monkeypatch.setattr(settings,"data_dir",str(tmp_path))
    person=client.post("/api/people",headers=auth,json={"first_name":"Dateitest"}).json()["id"]
    event=client.post("/api/events",headers=auth,json={"title":"Dateitest","starts_at":"2027-01-01T10:00:00Z"}).json()["id"]
    for url,get_url in [(f"/api/people/{person}/photo",None),(f"/api/events/{event}/photos",f"/api/events/{event}/photos")]:
        uploaded=client.post(url,headers=auth,files={"file":("photo.jpg",image_bytes("JPEG"))})
        assert uploaded.status_code in (200,201),uploaded.text
        path=url if get_url is None else get_url+"/"+uploaded.json()["id"]+"/image"
        result=client.get(path,headers=auth)
        assert result.status_code==200 and "no-store" in result.headers["cache-control"]
        with Image.open(BytesIO(result.content)) as saved:
            assert saved.format=="JPEG" and not saved.getexif()
    outside=tmp_path/"outside.jpg"
    outside.write_bytes(b"private")
    with Session(engine) as db:
        row=db.get(Person,person)
        key=row.photo_key
        row.photo_key=str(outside)
        db.commit()
    assert client.get(f"/api/people/{person}/photo",headers=auth).status_code==409
    assert client.delete(f"/api/people/{person}/photo",headers=auth).status_code==409
    assert outside.read_bytes()==b"private"
    with Session(engine) as db:
        db.get(Person,person).photo_key=key
        db.commit()
    assert client.delete(f"/api/people/{person}/photo",headers=auth).status_code==200
    assert client.delete(f"/api/events/{event}",headers=auth).status_code==204
    assert list((tmp_path/"event-photos").iterdir())==[]


def test_parser_deadline_and_program_allowlist(tmp_path,monkeypatch):
    with pytest.raises(ValueError,match="Unzulässiges"):
        document_routes.run_local(["sh"],tmp_path)
    ticks=iter([0,1,46])
    monkeypatch.setattr(document_routes.time,"monotonic",lambda:next(ticks))
    monkeypatch.setattr(document_routes,"run_local",lambda *args,**kwargs:"Pages: 1")
    with pytest.raises(Exception,match="Zeitlimit"):
        document_routes.extract_local(tmp_path/"source.pdf",".pdf",False,str(tmp_path))


def test_approved_parent_deletion_removes_photo(client,auth,tmp_path,monkeypatch):
    monkeypatch.setattr(settings,"data_dir",str(tmp_path))
    owner=client.get("/api/auth/me",headers=auth).json()["id"]
    pid=client.post("/api/people",headers=auth,json={"first_name":"Freigabefoto"}).json()["id"]
    photo=client.post(f"/api/people/{pid}/photo",headers=auth,files={"file":("photo.jpg",image_bytes("JPEG"))}).json()
    path=tmp_path/"people"/photo["photo_key"]
    assert path.is_file()
    with Session(engine) as db:
        approval=queue(db,owner,"person_delete",pid,"Person")["approval_id"]
    result=client.post("/api/approvals/"+approval+"/approve",headers=auth)
    assert result.status_code==200,result.text
    assert not path.exists()
    eid=client.post("/api/events",headers=auth,json={"title":"Freigabefoto","starts_at":"2027-01-01T10:00:00Z"}).json()["id"]
    photo_id=client.post(f"/api/events/{eid}/photos",headers=auth,files={"file":("photo.jpg",image_bytes("JPEG"))}).json()["id"]
    with Session(engine) as db:
        path=tmp_path/"event-photos"/db.get(EventPhoto,photo_id).file_key
        approval=queue(db,owner,"event_delete",eid,"Ereignis")["approval_id"]
    assert path.is_file()
    result=client.post("/api/approvals/"+approval+"/approve",headers=auth)
    assert result.status_code==200,result.text
    assert not path.exists()
    with Session(engine) as db:
        assert db.get(EventPhoto,photo_id) is None
