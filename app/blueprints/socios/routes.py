from flask import Blueprint, render_template, request, redirect, url_for, flash
from app import mongo, bcrypt, UserSession
from flask_login import login_user, logout_user, login_required, current_user
from datetime import datetime
from bson.objectid import ObjectId

socios = Blueprint('socios', __name__)

@socios.route('/')
def home():
    proximos = list(mongo.cx['partidos']['partidos'].find({"estado": "proximo"}).sort("fecha", 1).limit(3))
    return render_template('public/home.html', proximos=proximos)

@socios.route('/registro', methods=['GET', 'POST'])
def registro():
    if request.method == 'POST':
        dni = request.form.get('dni')
        email = request.form.get('email')
        
        
        db_socios = mongo.cx['socios']['socios']
        
        if db_socios.find_one({"dni": dni}):
            flash("El DNI ya se encuentra registrado.", "danger")
            return redirect(url_for('socios.registro'))
            
        if db_socios.find_one({"email": email}):
            flash("El correo electrónico ya está en uso.", "danger")
            return redirect(url_for('socios.registro'))
            
        pw_hash = bcrypt.generate_password_hash(request.form.get('password')).decode('utf-8')
        
        nuevo_socio = {
            "nombre": request.form.get('nombre'),
            "apellido": request.form.get('apellido'),
            "dni": dni,
            "fecha_nacimiento": request.form.get('fecha_nacimiento'),
            "direccion": request.form.get('direccion'),
            "telefono": request.form.get('telefono'),
            "email": email,
            "password_hash": pw_hash,
            "categoria": "Activo",
            "estado": "al_dia",
            "rol": "socio",
            "activo": True,
            "fecha_registro": datetime.now()
        }
        
        try:
            db_socios.insert_one(nuevo_socio)
            flash("¡Registro exitoso! Ya puedes iniciar sesión.", "success")
            return redirect(url_for('socios.login'))
        except Exception as e:
            print(f"Error: {e}")
            flash("Error de conexión.", "danger")
            return redirect(url_for('socios.registro'))
            
    return render_template('auth/registro.html')

@socios.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        dni = request.form.get('dni')
        password = request.form.get('password')
        
        user_data = mongo.cx['socios']['socios'].find_one({"dni": dni, "activo": True})
 
        if user_data and bcrypt.check_password_hash(user_data['password_hash'], password):
            login_user(UserSession(user_data))
            flash(f"¡Bienvenido, {user_data['nombre']}!", "success")
            
            if user_data.get('rol') == 'admin':
                return redirect(url_for('admin.dashboard'))
            return redirect(url_for('socios.perfil'))
        else:
            flash("Credenciales incorrectas o usuario dado de baja.", "danger")
            
    return render_template('auth/login.html')

@socios.route('/logout')
@login_required
def logout():
    logout_user()
    flash("Sesión cerrada.", "info")
    return redirect(url_for('socios.login'))

@socios.route('/perfil', methods=['GET', 'POST'])
@login_required
def perfil():
    socio = mongo.cx['socios']['socios'].find_one({"_id": ObjectId(current_user.id)})
    lista_partidos = list(mongo.cx['partidos']['partidos'].find({"estado": "proximo"}).sort("fecha", 1).limit(3))

    if request.method == 'POST':
        mongo.cx['socios']['socios'].update_one(
            {"_id": ObjectId(current_user.id)},
            {"$set": {
                "direccion": request.form.get('direccion'),
                "telefono": request.form.get('telefono'),
                "email": request.form.get('email')
            }}
        )
        flash("Perfil actualizado con éxito.", "success")
        return redirect(url_for('socios.perfil'))

    ultimo_pago_doc = mongo.cx['cuotas']['cuotas'].find_one(
        {"socio_id": ObjectId(current_user.id), "estado": "pagada"},
        sort=[("fecha_pago", -1)]
    )
    proxima_cuota = mongo.cx['cuotas']['cuotas'].find_one(
        {"socio_id": ObjectId(current_user.id), "estado": {"$in": ["pendiente", "vencida"]}},
        sort=[("fecha_vencimiento", 1)]
    )
    entradas_activas = mongo.cx['entradas']['entradas'].count_documents(
        {"socio_id": ObjectId(current_user.id), "estado": "valido"}
    )

    from datetime import timedelta
    venc = socio.get('fecha_registro')
    vencimiento_carnet = (venc + timedelta(days=730)).strftime('%m/%Y') if venc else '—'

    return render_template(
        'socios/perfil.html',
        socio=socio,
        proximos=lista_partidos,
        ultimo_pago=ultimo_pago_doc['monto'] if ultimo_pago_doc else None,
        proximo_venc=proxima_cuota['fecha_vencimiento'] if proxima_cuota else None,
        entradas_activas=entradas_activas,
        vencimiento_carnet=vencimiento_carnet
    )

@socios.route('/perfil/editar', methods=['GET', 'POST'])
@login_required
def editar_perfil():
    db_socios = mongo.cx['socios']['socios']
    socio = db_socios.find_one({"_id": ObjectId(current_user.id)})

    if request.method == 'POST':
        nuevo_email = request.form.get('email', '').strip()
        nuevo_telefono = request.form.get('telefono', '').strip()
        nueva_direccion = request.form.get('direccion', '').strip()
        password_actual = request.form.get('password_actual', '')
        nuevo_password = request.form.get('nuevo_password', '')
        confirmar_password = request.form.get('confirmar_password', '')

        # Validar email único (ignorar el propio)
        if nuevo_email != socio['email']:
            if db_socios.find_one({"email": nuevo_email, "_id": {"$ne": ObjectId(current_user.id)}}):
                flash("Ese correo ya está en uso por otro socio.", "danger")
                return render_template('socios/editar_perfil.html', socio=socio)

        campos = {
            "email": nuevo_email,
            "telefono": nuevo_telefono,
            "direccion": nueva_direccion,
        }

        # Cambio de contraseña (opcional)
        if nuevo_password:
            if not bcrypt.check_password_hash(socio['password_hash'], password_actual):
                flash("La contraseña actual es incorrecta.", "danger")
                return render_template('socios/editar_perfil.html', socio=socio)
            if nuevo_password != confirmar_password:
                flash("Las contraseñas nuevas no coinciden.", "danger")
                return render_template('socios/editar_perfil.html', socio=socio)
            campos["password_hash"] = bcrypt.generate_password_hash(nuevo_password).decode('utf-8')

        db_socios.update_one({"_id": ObjectId(current_user.id)}, {"$set": campos})
        flash("Datos actualizados con éxito.", "success")
        return redirect(url_for('socios.perfil'))

    return render_template('socios/editar_perfil.html', socio=socio)


@socios.route('/carnet')
@login_required
def carnet():
     #Carnet digital con QR único (pasamos el ID como string para que el HTML genere el QR)
    socio = mongo.cx['socios']['socios'].find_one({"_id": ObjectId(current_user.id)})
    return render_template('socios/carnet.html', socio=socio, qr_data=f"SOCIO-{socio['dni']}")