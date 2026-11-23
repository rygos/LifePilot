# Administration

## Rollen und Benutzer

Benutzer mit der Rolle `admin` sehen in der Navigation den Bereich **Administration**. Dort können sie vorhandene Konten zu Administratoren machen oder Administratorrechte entziehen. Mindestens ein Administratorkonto bleibt aktiv. Änderungen werden im Audit-Verlauf gespeichert.

Bei einer Neuinstallation erhält das erste durch die Bootstrap-Konfiguration angelegte Konto Administratorrechte. Weitere Konten starten mit der Rolle `user`.

## App aus Portainer aktualisieren

Der Updateknopf verwendet den Git-Webhook des Portainer-Stacks `lifepilot`. Der Stack muss aus `https://github.com/rygos/LifePilot.git`, Branch `main`, und `docker-compose.portainer.yml` bereitgestellt sein. Portainer lädt bei einem Update den aktuellen Commit und baut die Web- und API-Images neu. Vor dem Start der API führt `apps/api/entrypoint.sh` `alembic upgrade head` aus; erst danach starten REST-API und MCP-Dienst.

Im Adminbereich vergleicht LifePilot die beim API-Image-Bau eingebettete Commit-ID mit dem öffentlichen GitHub-Branch `main`. Beim Update über LifePilot übergibt der Webhook die geprüfte Ziel-Commit-ID an den API-Build. So bleibt die Versionsnummer auch dann korrekt, wenn sich nur Webdateien geändert haben und der Docker-Build sonst eine zwischengespeicherte API-Version verwenden würde. Bei neueren Commits erscheinen Anzahl und Betreffzeilen der Änderungen; die Anzeige ist auf die letzten 20 Commits begrenzt. Dazu benötigt der API-Build und -Container ausgehenden HTTPS-Zugriff auf `api.github.com`. Wenn die Versionsabfrage beim Build fehlschlägt, bleibt das Image trotzdem baubar; die Commitanzeige ist dann vorübergehend nicht verfügbar und der Updateknopf bleibt nutzbar. Der Portainer-Build-Kontext bleibt auf `apps/api` begrenzt und braucht kein `.git`-Verzeichnis.

Beim Start fordert der Updateknopf Portainer an und speichert Zielversion und vorherige Image-IDs im persistenten Datenvolume. Mit aktivierter Portainer-Statusanbindung zeigt die Administration für API, Weboberfläche, Auftragsverarbeitung, Erinnerungsplanung, Datenbank und Warteschlange den Containerzustand, Bereitschaft, Startzeit und Imagewechsel. Für die vier LifePilot-Dienste wird zusätzlich geprüft, ob die laufende Commit-ID der angeforderten Version entspricht. Datenbank und Warteschlange können korrekt als „Image unverändert“ erscheinen, wenn Portainer dasselbe Image wiederverwendet hat. Der Updateknopf meldet Erfolg erst, wenn alle Container wieder laufen und die vier LifePilot-Dienste die Zielversion melden. Ohne Portainer-Statusanbindung bleibt die bisherige API-Versionsprüfung verfügbar.

Für die Containerübersicht braucht LifePilot einen Portainer-API-Zugang mit Leserechten auf das Docker-Environment. Portainer unterstützt API-Schlüssel über den Header `X-API-Key` und stellt die Docker-Containerliste über sein Environment-Proxy bereit ([Portainer API-Zugriff](https://docs.portainer.io/api/access), [Docker-API-Beispiele](https://docs.portainer.io/api/examples)). Lege dafür in Portainer einen separaten Benutzer an, der nur Zugriff auf das LifePilot-Environment hat, erstelle für diesen Benutzer einen API-Schlüssel und hinterlege diese Stack-Variablen:

```text
PORTAINER_API_URL=http://portainer:9000
PORTAINER_API_KEY=<API-Schlüssel>
PORTAINER_ENDPOINT_ID=<Environment-ID>
PORTAINER_STACK_NAME=lifepilot
```

Die Portainer-Adresse muss aus dem API-Container erreichbar sein. Die Environment-ID steht in Portainer bei den Environments. `PORTAINER_STACK_NAME` muss dem Compose-Projektnamen des Stacks entsprechen. Das vorhandene interne Netzwerk `lifepilot-portainer-control` wird bereits vom API-Container verwendet. Der Schlüssel wird nur serverseitig gespeichert und nie an den Browser ausgegeben.

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
