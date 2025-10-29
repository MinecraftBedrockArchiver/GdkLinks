from msal import PublicClientApplication, SerializableTokenCache
import requests, os, json, subprocess

debug = False

urls_filename = "urls.json"
urls_min_filename = "urls.min.json"

cache_filename = "token_cache.bin"

# Content IDs for different Minecraft versions
versions = {
	"release": "7792d9ce-355a-493c-afbd-768f4a77c3b0",
	"preview": "98bd2335-9b01-4e4c-bd05-ccc01614078b"
}

# Get Xbox Live token header
def get_xbox_token() -> str:
	# Load the token cache if it exists
	cache = SerializableTokenCache()
	if os.path.exists(cache_filename):
		cache.deserialize(open(cache_filename, "r").read())

	app = PublicClientApplication(
		"b3900558-4f9d-43ef-9db5-cfc7cb01874e",
		authority="https://login.microsoftonline.com/consumers",
		token_cache=cache)

	# Auth from cache or interactive if debug
	accounts = app.get_accounts()
	if not accounts:
		if (debug):
			result = app.acquire_token_interactive(scopes=["XboxLive.signin"], prompt="select_account")
		else:
			print("No accounts found. Exiting.")
			exit(1)
	else:
		result = app.acquire_token_silent(["XboxLive.signin"], account=accounts[0])

	if "access_token" not in result:
		print(result.get("error"))
		print(result.get("error_description"))
		print(result.get("correlation_id"))
		exit(1)

	# Cache the token
	with open(cache_filename, "w") as f:
		f.write(cache.serialize())

	msa_token = result["access_token"]

	if (debug): print("Access token is " + msa_token)

	# Xbox auth
	response = requests.post("https://user.auth.xboxlive.com/user/authenticate", json={
		"Properties": {
			"AuthMethod": "RPS",
			"SiteName": "user.auth.xboxlive.com",
			"RpsTicket": f"d={msa_token}"
		},
		"RelyingParty": "http://auth.xboxlive.com",
		"TokenType": "JWT"
	}).json()

	xbox_token = response['Token']

	if (debug): print("Xbox Live token: " + xbox_token)

	# XSTS auth
	response = requests.post("https://xsts.auth.xboxlive.com/xsts/authorize", json={
		"Properties": {
			"SandboxId": "RETAIL",
			"UserTokens": [xbox_token]
		},
		"RelyingParty": "http://update.xboxlive.com",
		"TokenType": "JWT"
	}).json()

	xsts_uhs = response['DisplayClaims']['xui'][0]['uhs']
	xsts_token = response['Token']

	token_header = f"XBL3.0 x={xsts_uhs};{xsts_token}"

	if (debug): print("XSTS Token Header: " + token_header)

	return token_header

# Extract version from filename
def get_version(name: str) -> str:
	raw_ver = name.split("_")[1]
	ver_parts = raw_ver.split('.')

	ver_parts[2] = ver_parts[2].rjust(2, '0')
	first_bit = ver_parts[2][:-2] or "0"
	last_bit = ver_parts[2][-2:].lstrip('0') or "0"
	return f"{ver_parts[0]}.{ver_parts[1]}.{first_bit}.{last_bit}"

# Default urls structure if none exists
urls = {
	version_name: {} for version_name in versions.keys()
}
# Load existing urls if present
if os.path.exists(urls_filename):
	urls = json.load(open(urls_filename, "r"))

token_header = get_xbox_token()

has_changes = False

for edition_name, content_id in versions.items():
	response = requests.get(
		f"https://packagespc.xboxlive.com/GetBasePackage/{content_id}",
		headers={
			"Authorization": token_header,
			"User-Agent": "MinecraftBedrockArchiver/1.0", # We can't use the default UA
		}
	).json()

	# Process each package file
	for package in response['PackageFiles']:
		if not package['FileName'].endswith('.msixvc'):
			continue

		version = get_version(package['FileName'])

		print(f"Found {edition_name} {version}")
		
		if version in urls[edition_name]:
			print(f"Already have this version, skipping")
			continue
		
		found_urls = []
		for root_path in package['CdnRootPaths']:
			full_url = root_path + package['RelativeUrl']
			found_urls.append(full_url)
		
		urls[edition_name][version] = found_urls

		# Save urls to file
		with open(urls_filename, "w") as f:
			json.dump(urls, f, indent=4)
		with open(urls_min_filename, "w") as f:
			json.dump(urls, f)

		# Create a commit with changes
		commit_message = f"Add {edition_name} {version}"
		if (debug): print(f"Would commit with message: {commit_message}")
		if not (debug): subprocess.run(["git", "add", urls_filename, urls_min_filename])
		if not (debug): subprocess.run(["git", "-c", "user.name='github-actions[bot]'", "-c", "user.email='github-actions[bot]@users.noreply.github.com'", "commit", "-m", commit_message])
		has_changes = True

# Push changes if any
if has_changes:
	if not (debug): subprocess.run(["git", "push", "origin"])
