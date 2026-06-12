import mysql.connector
import bcrypt

# Database config
DB_CONFIG = {
    'host': 'localhost',
    'user': 'root',
    'password': 'root',  # Your MySQL password
    'database': 'ssuet_ai_db'
}

# Admin credentials
admin_email = 'admin@ssuet.edu.pk'
admin_password = 'admin123'
admin_name = 'Admin User'
admin_phone = '0300-0000000'

# Hash password
password_hash = bcrypt.hashpw(admin_password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

# Connect to database
conn = mysql.connector.connect(**DB_CONFIG)
cursor = conn.cursor()

# Check if admin exists
cursor.execute("SELECT id FROM users WHERE email = %s", (admin_email,))
if cursor.fetchone():
    print("⚠️ Admin already exists!")
else:
    # Insert admin
    cursor.execute(
        "INSERT INTO users (name, email, phone, password_hash) VALUES (%s, %s, %s, %s)",
        (admin_name, admin_email, admin_phone, password_hash)
    )
    conn.commit()
    print("✅ Admin account created successfully!")
    print(f"   Email: {admin_email}")
    print(f"   Password: {admin_password}")

cursor.close()
conn.close()
