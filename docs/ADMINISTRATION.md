# Administration

## Rollen und Benutzer

Benutzer mit der Rolle `admin` sehen in der Navigation den Bereich **Administration**. Dort können sie vorhandene Konten zu Administratoren machen oder Administratorrechte entziehen. Mindestens ein Administratorkonto bleibt aktiv. Änderungen werden im Audit-Verlauf gespeichert.

Bei einer Neuinstallation erhält das erste durch die Bootstrap-Konfiguration angelegte Konto Administratorrechte. Weitere Konten starten mit der Rolle `user`.

## App aus Portainer aktualisieren

Der Updateknopf verwendet den Git-Webhook des Portainer-Stacks `lifepilot`. Der Stack muss aus `https://github.com/rygos/LifePilot.git`, Branch `main`, und `docker-compose.portainer.yml` bereitgestellt sein. Portainer lädt bei einem Update den aktuellen Commit und baut die Web- und API-Images neu. Vor dem Start der API führt `apps/api/entrypoint.sh` `alembic upgrade head` aus; erst danach starten REST-API und MCP-Dienst.

Im Adminbereich vergleicht LifePilot die beim API-Image-Bau eingebettete Commit-ID mit dem öffentlichen GitHub-Branch `main`. Bei neueren Commits erscheinen Anzahl und Betreffzeilen der Änderungen; die Anzeige ist auf die letzten 20 Commits begrenzt. Dazu benötigt der API-Build und -Container ausgehenden HTTPS-Zugriff auf `api.github.com`. Wenn die Versionsabfrage beim Build fehlschlägt, bleibt das Image trotzdem baubar; die Commitanzeige ist dann vorübergehend nicht verfügbar und der Updateknopf bleibt nutzbar. Der Portainer-Build-Kontext bleibt auf `apps/api` begrenzt und braucht kein `.git`-Verzeichnis.

Einmalige Vorbereitung für den Portainer-Server:

```sh
docker network create --internal lifepilot-portainer-control
docker network connect --alias portainer lifepilot-portainer-control portainer
```

Der Portainer-Stack braucht einen Git-Webhook unter **GitOps updates → Webhook**. Die dazugehörige UUID wird als geheime Servervariable `PORTAINER_WEBHOOK_URL` in der Stack-Konfiguration hinterlegt:

```text
http://portainer:9000/api/stacks/webhooks/<WEBHOOK-UUID>
```

Der Webhook ist nur über das interne Docker-Netzwerk `lifepilot-portainer-control` erreichbar. Im Portainer-Stack muss die GitOps-Aktualisierung mit dieser Webhook-UUID aktiviert sein. Der Webhook startet das Stack-Update; er gewährt keinen Zugriff auf andere Portainer-API-Funktionen.

Das Update kann die Oberfläche für die Dauer des Image-Builds und Neustarts kurz unterbrechen. Der Adminbereich bestätigt, dass Portainer die Anforderung angenommen hat. Anschließend kann die Seite nach etwa einer Minute neu geladen werden.
