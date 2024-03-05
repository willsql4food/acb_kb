Remove-Item C:\source\keys\fnd-cloud-project-b2a8d27db4f3.json
# This is incomplete JSON from a Google key file - update this to the actual contents you need to write
# NOTE - backslashes can be mangled in a web-interface Powershell execution, hence the use of &bsol; in the JSON
#         and the subsequent replacement call when the payload gets to the actual machine
'{
    "type": "service_account",
    "project_id": "",
    "private_key_id": "",
    "private_key": "-----BEGIN PRIVATE KEY-----&bsol;-----END PRIVATE KEY-----&bsol;n",
    "client_email": "",
    "client_id": "102730727004241975119",
    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
    "token_uri": "https://oauth2.googleapis.com/token",
    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
    "client_x509_cert_url": "https://www.googleapis.com/robot/v1/metadata/x509/ga4-access%40fnd-cloud-project.iam.gserviceaccount.com",
    "universe_domain": "googleapis.com"
  }' `
| Out-File -FilePath C:\source\keys\fnd-cloud-project-b2a8d27db4f3.json -Encoding ascii

Get-Content -Path C:\source\keys\fnd-cloud-project-b2a8d27db4f3.json