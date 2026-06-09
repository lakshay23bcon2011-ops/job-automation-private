from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']

flow = InstalledAppFlow.from_client_secrets_file('data_folder/credentials.json', SCOPES)
creds = flow.run_local_server(port=0)

with open('data_folder/gmail_token.json', 'w', encoding='utf-8') as f:
    f.write(creds.to_json())

print('data_folder/gmail_token.json created successfully!')