import mysql.connector
import bcrypt

# ⚠️ CONFIGURATION - Change the password here if it's not 'root'
DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': 'root',  # <--- Change this to your actual MySQL password
    'database': 'ssuet_ai_db'
}

ADMIN_EMAIL = 'admin@ssuet.edu.pk'
ADMIN_PASSWORD = 'admin123'

def run_setup():
    try:
        print("Connecting to MySQL...")
        conn = mysql.connector.connect(**DB_CONFIG)
        cursor = conn.cursor()

        # 1. Generate a FRESH hash on your local machine
        print(f"Generating fresh hash for: {ADMIN_PASSWORD}...")
        hashed = bcrypt.hashpw(ADMIN_PASSWORD.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

        # 2. Clean up old admin records
        print("Cleaning old admin data...")
        cursor.execute("DELETE FROM users WHERE email = %s", (ADMIN_EMAIL,))
        cursor.execute("DELETE FROM admins WHERE email = %s", (ADMIN_EMAIL,))
        
        # 3. Insert into USERS table (Crucial: Login page checks this table!)
        print("Inserting into users table...")
        cursor.execute(
            "INSERT INTO users (name, email, phone, password_hash) VALUES (%s, %s, %s, %s)",
            ('Admin User', ADMIN_EMAIL, '0300-0000000', hashed)
        )
        
        # 4. Insert into ADMINS table (For dashboard permissions)
        print("Inserting into admins table...")
        cursor.execute(
            "INSERT INTO admins (username, password_hash, email) VALUES (%s, %s, %s)",
            ('admin', hashed, ADMIN_EMAIL)
        )
        
        conn.commit()
        print("\n" + "="*30)
        print("✅ SUCCESS!")
        print(f"Login Email: {ADMIN_EMAIL}")
        print(f"Login Password: {ADMIN_PASSWORD}")
        print("="*30)
        print("Now restart your Flask server and try logging in.")

        cursor.close()
        conn.close()

    except Exception as e:
        print(f"❌ ERROR: {e}")

if __name__ == "__main__":
    run_setup()
