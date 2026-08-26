import os
from flask import Flask
from flask_bcrypt import Bcrypt
from pymongo import MongoClient
from datetime import datetime

bcrypt = Bcrypt()

# Lee la URI desde Render o usa localhost en desarrollo local
mongo_uri = os.environ.get('MONGO_URI', 'mongodb://localhost:27017/')
client = MongoClient(mongo_uri)
db_socios = client['socios']['socios']

def generar_admin():
    dni_admin = "11111111" 
    
    existe = db_socios.find_one({"dni": dni_admin})
    if existe:
        print("El Administrador ya se encuentra registrado en la base de datos.")
        return

    password_plana = "admin123"
    password_hasheada = bcrypt.generate_password_hash(password_plana).decode('utf-8')

    admin_data = {
        "nombre": "Director",
        "apellido": "General",
        "dni": dni_admin,
        "email": "admin@club.com",
        "password_hash": password_hasheada,
        "categoria": "Activo",
        "estado": "al_dia",
        "rol": "admin",  
        "activo": True,
        "fecha_registro": datetime.now()
    }

    db_socios.insert_one(admin_data)
    print(f"Credenciales de acceso:\n   DNI: {dni_admin}\n   Clave: {password_plana}")

if __name__ == "__main__":
    generar_admin()