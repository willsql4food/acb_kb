import pgpy
from pgpy.constants import PubKeyAlgorithm, KeyFlags, HashAlgorithm, SymmetricKeyAlgorithm, CompressionAlgorithm
import base64
import io
import os

# =============================================================================
# Functions for handling private keys
# =============================================================================
def get_key_from_vault():
    # Use when the private key is stored in Azure Key Vault 
    # 
    # Fetch the base 64 encoded value
    base64 = "Read this from the key vault..."
    # Decode this from base 64 and interpret as ASCII
    ret = base64.b64decode(base64).decode("ascii").lstrip()
    return str(ret)

def get_key_from_file(filename):
    # Use when the private key is stored in a file
    # 
    # Fetch the private key text
    with open(filename, 'r') as pk:
        txt = pk.read().lstrip()
    private_key = pgpy.PGPKey()
    private_key.parse(txt)
    return private_key
    

# Run through a directory and see if the files in it are public or private keys, 
# and if the passphrase unlocks them
def check_files_for_keys(path, passphrase):
    keys = os.listdir(path)

    files = [f for f in keys if os.path.isfile(f"{path}{f}")]

    for f in files:
        k = f"{path}{f}"
        print(f"=============================================================================\nWorking file [{k}]")
        try:
            private_key = get_key_from_file(k)
            if private_key.is_public:
                desc = 'Public'
            else:
                desc = 'Private'

            print(f"\t{desc} key is protected: {private_key.is_protected}")
            print(f"\t{desc} key is already unlocked: {private_key.is_unlocked}")
            with private_key.unlock(passphrase=passphrase):
                print(f"\tAfter unlock call, {desc} key is unlocked: {private_key.is_unlocked}")

        except:
            print("\tFailed - invalid file")
        

# =============================================================================
keypath = 'C:/source/keys/PLCC/'
keyfile = keypath + 'fnd_pgp_dev_rsa.key'

datapath = 'C:/source/repos/__temp/PLCC/PGP/'
outpath = 'C:/source/repos/__temp/PLCC/Decrypted/'
passphrase = ''

# check_files_for_keys(keypath, passphrase)

# Use the key to decrypt the files
fso = os.listdir(datapath)
# print(*fso, sep='\n')

files = [f for f in fso if os.path.isfile(f"{datapath}{f}")]
# print(*files, sep='\n')

if not os.path.exists(outpath):
    os.mkdir(outpath)

for f in files:
    print(f"=============================================================================\nDecrypting: [{datapath}{f}]")
    enc_msg = pgpy.PGPMessage.from_file(datapath + f)

    private_key = get_key_from_file(keyfile)
    with private_key.unlock(passphrase):
        dec_msg = private_key.decrypt(enc_msg).message.decode()

    out = outpath + f.replace(".PGP", "")
    with open(out, "w") as outfile:
        outfile.write(dec_msg)
    print(f"\tOutput: [{outfile.name}]")
