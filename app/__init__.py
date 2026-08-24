from flask import Flask
from flask_bcrypt import Bcrypt
from flask_login import LoginManager, UserMixin
from flask_pymongo import PyMongo
from bson.objectid import ObjectId

bcrypt = Bcrypt()
login_manager = LoginManager()
login_manager.login_view = 'socios.login'

# Inicializamos PyMongo sin asignarle app todavía
mongo = PyMongo()

class UserSession(UserMixin):
    def __init__(self, user_dict):
        self.id = str(user_dict['_id'])
        self.nombre = user_dict.get('nombre')
        self.apellido = user_dict.get('apellido')
        self.rol = user_dict.get('rol', 'socio')

@login_manager.user_loader
def load_user(user_id):
    try:
        user_data = mongo.cx['socios']['socios'].find_one({"_id": ObjectId(user_id), "activo": True})
        if user_data:
            return UserSession(user_data)
    except Exception:
        return None
    return None

def create_app():
    app = Flask(__name__)
    app.config.from_object('config.Config')

    mongo.init_app(app)
    bcrypt.init_app(app)
    login_manager.init_app(app)

    # Registro de TODOS los Blueprints del sistema
    from .blueprints.socios.routes import socios
    from .blueprints.admin.routes import admin
    from .blueprints.entradas.routes import entradas
    from .blueprints.cuotas.routes import cuotas
    from .blueprints.partidos.routes import partidos

    app.register_blueprint(socios)
    app.register_blueprint(admin)
    app.register_blueprint(entradas)
    app.register_blueprint(cuotas)
    app.register_blueprint(partidos)

    return app