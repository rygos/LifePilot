from io import BytesIO
from uuid import uuid4
import json
import shutil

import pytest
from PIL import Image
from sqlalchemy.orm import Session

from lifepilot.config import settings
from lifepilot.db import engine
from lifepilot.models import DocumentIndex, DocumentPage, User
from lifepilot.security import create_token
from lifepilot import document_routes, capture_ai


def upload(client,auth,mid,name,body):
    response=client.post("/api/attachments",headers=auth,data={"resource_type":"memory","resource_id":mid},files={"file":(name,body)})
    assert response.status_code==201,response.text
    return response.json()["id"]


def test_document_index_search_capture_and_removal(client,auth,tmp_path,monkeypatch):
    monkeypatch.setattr(settings,"data_dir",str(tmp_path))
    monkeypatch.setattr(settings,"llm_base_url","")
    mid=client.post("/api/memories",headers=auth,json={"title":"Dokumenttest","content":"Test"}).json()["id"]
    original=b"Frist 12.01.2027\n100% korrekt\n"
    aid=upload(client,auth,mid,"frist.txt",original)
    path="/api/documents/"+aid
    with Session(engine) as db:
        other=User(username="doc-"+uuid4().hex,password_hash="unused")
        db.add(other);db.commit()
        foreign={"Authorization":"Bearer "+create_token(other.id)}
    assert client.get(path,headers=foreign).status_code==404
    assert client.post(path+"/extract",headers=foreign,json={}).status_code==404
    assert client.get(path,headers=auth).json()["indexed"] is False
    result=client.post(path+"/extract",headers=auth,json={})
    assert result.status_code==200,result.text
    detail=result.json()
    assert not detail["partial"] and detail["total_pages"]==1
    assert detail["pages"][0]["text"]==original.decode().strip()
    for query in ("frist","100%"):
        hits=client.get("/api/documents/search",headers=auth,params={"q":query}).json()
        assert any(row["id"]==aid and row["page"]==1 for row in hits)
    assert client.get("/api/documents/search",headers=foreign,params={"q":"frist"}).json()==[]
    assert client.get("/api/documents/search",headers=auth,params={"q":"100_"}).json()==[]
    assert client.post(path+"/capture",headers=auth,json={"page":1,"digest":detail["digest"],"quote":"fake"}).status_code==422
    payload={"page":1,"digest":detail["digest"],"quote":"Frist 12.01.2027"}
    first=client.post(path+"/capture",headers=auth,json=payload)
    assert first.status_code==201,first.text
    assert client.post(path+"/capture",headers=auth,json=payload).json()==first.json()
    assert client.post(path+"/capture",headers=auth,json={**payload,"digest":"0"*64}).status_code==409
    assert client.get("/api/attachments/"+aid+"/download",headers=auth).content==original
    assert client.delete(path+"/index",headers=auth).status_code==204
    assert client.get(path,headers=auth).json()["indexed"] is False
    assert client.post(path+"/extract",headers=auth,json={}).status_code==200
    assert client.delete("/api/memories/"+mid,headers=auth).status_code==204
    with Session(engine) as db:
        assert db.get(DocumentIndex,aid) is None
        assert db.get(DocumentPage,(aid,1)) is None


def pdf_bytes():
    stream=b"BT /F1 18 Tf 40 100 Td (LifePilot PDF Test) Tj ET"
    objects=[b"<< /Type /Catalog /Pages 2 0 R >>",b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",b"<< /Length "+str(len(stream)).encode()+b" >>\nstream\n"+stream+b"\nendstream"]
    result=b"%PDF-1.4\n"
    offsets=[0]
    for i,obj in enumerate(objects,1):
        offsets.append(len(result))
        result+=str(i).encode()+b" 0 obj\n"+obj+b"\nendobj\n"
    xref=len(result)
    result+=b"xref\n0 6\n0000000000 65535 f \n"+b"".join(f"{x:010d} 00000 n \n".encode() for x in offsets[1:])
    return result+b"trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n"+str(xref).encode()+b"\n%%EOF\n"


def test_native_pdf_and_explicit_ocr(client,auth,tmp_path,monkeypatch):
    monkeypatch.setattr(settings,"data_dir",str(tmp_path))
    mid=client.post("/api/memories",headers=auth,json={"title":"PDF Test","content":"Test"}).json()["id"]
    if not all(shutil.which(x) for x in ("prlimit","pdfinfo","pdftotext")):
        pytest.skip("Lokale PDF-Programme fehlen")
    aid=upload(client,auth,mid,"test.pdf",pdf_bytes())
    result=client.post("/api/documents/"+aid+"/extract",headers=auth,json={})
    assert result.status_code==200,result.text
    assert result.json()["pages"][0]["text"]=="LifePilot PDF Test"
    image=BytesIO()
    Image.new("RGB",(200,100),"white").save(image,format="PNG")
    picture=upload(client,auth,mid,"scan.png",image.getvalue())
    path="/api/documents/"+picture+"/extract"
    assert client.post(path,headers=auth,json={}).status_code==422
    calls=[]
    def mocked(args,directory,timeout=12):
        calls.append(args)
        return "OCR Test"
    monkeypatch.setattr(document_routes,"run_local",mocked)
    result=client.post(path,headers=auth,json={"ocr":True})
    assert result.status_code==200,result.text
    assert result.json()["pages"][0]["method"]=="ocr" and calls[0][0]=="tesseract"
    assert client.delete("/api/memories/"+mid,headers=auth).status_code==204


def test_document_suggestions_require_confirmation(monkeypatch):
    monkeypatch.setattr(settings,"llm_base_url","http://model.invalid/v1")
    monkeypatch.setattr(settings,"llm_model","test")
    suggestions=[{"kind":"task","title":"Frist","content":"Frist prüfen"},
        {"kind":"owner_relationship","title":"Falsche Zuordnung","content":"Mein Kollege","person_name":"Anna"}]
    monkeypatch.setattr(capture_ai,"urlopen",lambda *a,**kw: BytesIO(json.dumps({"choices":[{"message":{"content":json.dumps({"suggestions":suggestions})}}]}).encode()))
    result=capture_ai.extract_facts(document_routes.MARKER+"\nFrist prüfen")
    assert [row.kind for row in result]==["task"] and result[0].confirmation_required


def test_real_ocr_if_installed(tmp_path):
    import subprocess
    from PIL import ImageDraw, ImageFont
    if not all(shutil.which(x) for x in ("prlimit","tesseract","pdftoppm","pdfinfo","pdftotext")):
        pytest.skip("Lokale OCR-Programme fehlen")
    languages=subprocess.run(["tesseract","--list-langs"],capture_output=True,text=True,timeout=10,check=True).stdout.splitlines()
    if not {"deu","eng"}.issubset(languages):
        pytest.skip("OCR-Sprachpakete deu/eng fehlen")
    image=Image.new("RGB",(1200,300),"white")
    ImageDraw.Draw(image).text((60,80),"LIFEPILOT TEST 123",font=ImageFont.load_default(size=56),fill="black")
    png=tmp_path/"source.png"
    image.save(png)
    total,pages=document_routes.extract_local(png,".png",True,str(tmp_path))
    assert total==1 and "LIFEPILOT TEST 123" in pages[0][1].upper()
    pdf=tmp_path/"source.pdf"
    image.save(pdf,format="PDF")
    total,pages=document_routes.extract_local(pdf,".pdf",True,str(tmp_path))
    assert total==1 and pages[0][2]=="ocr" and "LIFEPILOT TEST 123" in pages[0][1].upper()
