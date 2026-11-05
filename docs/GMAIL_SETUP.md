# Gmail payment notification setup

Use a dedicated demo Gmail account. No billing or paid quota increase is needed. Until configured, `MAIL_MODE=preview` shows the notification inside Purchasing and sends no email.

1. Create a project at [Google Cloud Console](https://console.cloud.google.com/). Enable **Gmail API** from APIs and Services. Keep billing disabled.
2. Configure **Google Auth Platform** with the app name and sender/support email. Select the audience appropriate to your account. In Testing mode, add the sender account as a test user.
3. Create an OAuth **Web application** client. Add `https://developers.google.com/oauthplayground` as an authorized redirect URI.
4. In [OAuth Playground](https://developers.google.com/oauthplayground), open Settings and select **Use your own OAuth credentials**. Enter the client ID and client secret there.
5. Request scope `https://www.googleapis.com/auth/gmail.send`. Authorize using the dedicated sender account. Exchange the authorization code for tokens.
6. Copy the refresh token into the git-ignored root `.env.local`. Never paste tokens into chat or commit them.

```dotenv
MAIL_MODE=gmail
MAIL_FROM=your-demo-sender@gmail.com
MAIL_ALLOWED_RECIPIENTS=your-controlled-test-recipient@example.com
GMAIL_CLIENT_ID=your-client-id
GMAIL_CLIENT_SECRET=your-client-secret
GMAIL_REFRESH_TOKEN=your-refresh-token
```

The sender must match the authorized mailbox or a permitted sending alias. Separate multiple allowed demo recipients with commas. The vendor's actual account email must be on that list. This prevents the public demo from sending to arbitrary addresses.

7. Restart the local API. For cloud delivery, enter these values into Vercel Production environment variables using the dashboard or `vercel env add`; then redeploy. A local `.env.local` change alone does not configure Vercel.
8. In Purchasing, complete L1 and finance approval with separate accounts. Record a simulated payment. The UI shows `accepted` only after Gmail accepts the API request. Inspect the recipient inbox to verify delivery.

Testing-mode refresh tokens can expire after seven days. Follow Google's consent/verification requirements when moving beyond a personal test. Never enable billing as a workaround.

If authorization fails, fix the sender configuration and use **Retry notification**. If status is `delivery_unknown`, inspect the sender mailbox first: the request may already have sent the message. The app deliberately prevents blind retries of uncertain sends. A failed email does not undo or repeat the payment record.

References: [Gmail message sending](https://developers.google.com/workspace/gmail/api/guides/sending), [OAuth offline access](https://developers.google.com/identity/protocols/oauth2/web-server#offline).
