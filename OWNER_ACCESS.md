# Owner access

Visitors can use Main dashboard without signing in. Admin / Research is
hidden and denied until the owner signs in.

## Set your password

In Streamlit Community Cloud, open your app's settings and Secrets editor.
Append this section after your existing secrets, without replacing API keys:

```toml
[admin]
password = "REPLACE_WITH_YOUR_OWN_LONG_RANDOM_PASSWORD"
```

Replace the example with a unique password of at least 16 characters.
Do not commit your actual password or a secrets.toml file to GitHub.

Save the secrets, reload the app, expand **Owner sign in** in the sidebar,
and enter your password. Only authenticated sessions see the Main/Admin
switch. Use **Sign out of owner access** before sharing a device.

Owner sessions expire after eight hours. A changed or removed password
invalidates existing owner sessions when the app reloads the secret.
Missing, empty or short passwords keep admin access locked.
Failed sign-ins have a session-level retry delay; this is not a replacement
for account-based authentication and server-wide rate limits on a large
public deployment.

The shared `is_research()` check validates authorization on every rerun,
including the research sections in NFL, NBA, pick history and paper quotes.
The visitor dashboard and its existing pick-generation behavior remain available.

## Repository visibility

This login protects the running app's research UI. The GitHub repository
is currently public: source code, committed research files and repository
history remain readable on GitHub. Make the repository private separately
if those materials should also be private.

## Verification

`python -m unittest discover -s tests -p test_owner_access.py -v`

Authorization tests cover visitor denial, missing configuration, wrong passwords,
successful login, logout, session isolation, secret rotation, expiry and tampering.
