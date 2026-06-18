from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from app import mongo
from bson.objectid import ObjectId
from datetime import datetime

admin = Blueprint('admin', __name__, url_prefix='/admin')

# Este es un agreagado que le hice porque estaba en requisitos no funcionales :)
def admin_required(f):
    from functools import wraps
    @wraps(f)
    def dec(*args, **kwargs):
        if not current_user.is_authenticated or current_user.rol != 'admin':
            flash("Acceso denegado.", "danger")
            return redirect(url_for('socios.login'))
        return f(*args, **kwargs)
    return dec

# RF-A07: Dashboard General
@admin.route('/dashboard')
@login_required
@admin_required
def dashboard():
    db_socios = mongo.cx['socios']['socios']
    hoy = datetime.now()
    
    # 1. Estadísticas de Socios Reales
    activos = db_socios.count_documents({"activo": True, "estado": "al_dia"})
    mora = db_socios.count_documents({"activo": True, "estado": "mora"})
    
    # 2. Ingresos Mensuales Reales
    inicio_mes = datetime(hoy.year, hoy.month, 1)
    ingresos_cuotas_mes = sum(c['monto'] for c in mongo.cx['cuotas']['cuotas'].find({
        "estado": "pagada", 
        "fecha_pago": {"$gte": inicio_mes}
    }))
    ingresos_entradas_mes = sum(e['precio_pagado'] for e in mongo.cx['entradas']['entradas'].find({
        "fecha_compra": {"$gte": inicio_mes}
    }))
    ingresos_mensuales_totales = ingresos_cuotas_mes + ingresos_entradas_mes
    
    # 3. Próximo Partido e Insumos para la Tarjeta de Aforo y Seguridad
    proximo_partido = mongo.cx['partidos']['partidos'].find_one(
        {"estado": "proximo"}, 
        sort=[("fecha", 1)]
    )
    
    aforo_proximo = 0
    operativo_seguridad = {"policias": 0, "seguridad_privada": 0, "stewards": 0, "costo": 0.0, "rival": "A programar"}
    
    if proximo_partido:
        operativo_seguridad["rival"] = proximo_partido.get("rival", "Rival")
        # Calculo el aforo real sumando los tickets vendidos guardados en el partido
        aforo_proximo = sum(s.get("vendidos", 0) for s in proximo_partido.get("sectores", []))
        
        # Cruzo datos con el operativo policial real asignado en su disquito
        plan_seguridad = mongo.cx['operativos']['operativos'].find_one({"partido_id": proximo_partido["_id"]})
        if plan_seguridad:
            operativo_seguridad["policias"] = plan_seguridad.get("policias", 0)
            operativo_seguridad["seguridad_privada"] = plan_seguridad.get("seguridad_privada", 0)
            operativo_seguridad["stewards"] = plan_seguridad.get("stewards", 0)
            # Costo real según el personal cargado
            operativo_seguridad["costo"] = (
                (operativo_seguridad["policias"] * 1500) + 
                (operativo_seguridad["seguridad_privada"] * 1200) + 
                (operativo_seguridad["stewards"] * 1000)
            )

    # 4. RF-A10: Búsqueda y filtrado de socios de la tabla principal
    busqueda = request.args.get('q', '')
    query_socio = {"activo": True}
    if busqueda:
        query_socio["$or"] = [
            {"nombre": {"$regex": busqueda, "$options": "i"}},
            {"apellido": {"$regex": busqueda, "$options": "i"}},
            {"dni": busqueda}
        ]
    
    lista_socios = list(db_socios.find(query_socio))
    
    # 5. Mapeo para la línea de tiempo de Actividad Reciente
    logs_actividad = [
        {"texto": "Nuevo Socio Registrado", "subtexto": f"Total de activos: {activos}", "tiempo": "Actualizado recién", "icono": "bi-person-plus-fill", "color": "text-success"},
        {"texto": "Control de Morosidad", "subtexto": f"Socios con deuda: {mora}", "tiempo": "Sincronizado", "icono": "bi-exclamation-triangle-fill", "color": "text-danger"}
    ]
    
    return render_template(
        'admin/dashboard.html',
        activos=activos,
        mora=mora,
        ingresos=ingresos_mensuales_totales,
        aforo=aforo_proximo,
        operativo=operativo_seguridad,
        proximo_partido=proximo_partido,
        logs=logs_actividad,
        socios=lista_socios
    )

# RF-A02: CRUD Socios
@admin.route('/socios/baja/<socio_id>')
@login_required
@admin_required
def baja_socio(socio_id):
    mongo.cx['socios']['socios'].update_one({"_id": ObjectId(socio_id)}, {"$set": {"activo": False}})
    flash("Socio dado de baja del sistema (Baja lógica aplicada).", "warning")
    return redirect(url_for('admin.dashboard'))

# RF-A04: Gestión de Cuotas y Aranceles
@admin.route('/cuotas', methods=['GET', 'POST'])
@login_required
@admin_required
def gestionar_cuotas():
    db_cuotas = mongo.cx['cuotas']['cuotas']
    db_socios = mongo.cx['socios']['socios']
    hoy = datetime.now()
    
    if request.method == 'POST':
        dni    = request.form.get('dni')
        mes    = int(request.form.get('mes'))
        metodo = request.form.get('metodo', 'Efectivo')
        monto  = float(request.form.get('monto_manual') or 15500.0)

        socio = db_socios.find_one({"dni": dni})
        if socio:
            cuota_existente = db_cuotas.find_one({
                "socio_id": socio['_id'], "mes": mes, "anio": hoy.year,
                "estado": {"$in": ["pendiente", "vencida"]}
            })
            if cuota_existente:
                db_cuotas.update_one(
                    {"_id": cuota_existente['_id']},
                    {"$set": {"estado": "pagada", "fecha_pago": datetime.now(), "metodo_pago": metodo}}
                )
            else:
                db_cuotas.insert_one({
                    "socio_id": socio['_id'],
                    "mes": mes, "anio": hoy.year, "monto": monto,
                    "estado": "pagada",
                    "fecha_vencimiento": datetime(hoy.year, mes, 10),
                    "fecha_pago": datetime.now(),
                    "metodo_pago": metodo,
                    "paypal_order_id": None
                })

            deuda_restante = db_cuotas.find_one({"socio_id": socio['_id'], "estado": {"$in": ["pendiente", "vencida"]}})
            db_socios.update_one({"_id": socio['_id']}, {"$set": {"estado": "al_dia" if not deuda_restante else "mora"}})
            flash("Pago manual registrado con éxito en tesorería.", "success")
        else:
            flash("Socio inexistente. Verificá el DNI.", "danger")

        return redirect(url_for('admin.gestionar_cuotas'))
    
    # --- ESTADÍSTICAS EN TIEMPO REAL DESDE COMPASS Mi DISEÑO DE CUOTAS ---
    # 1. Recaudación Mensual Total
    recaudacion_mes = sum(c['monto'] for c in db_cuotas.find({"estado": "pagada", "fecha_pago": {"$gte": datetime(hoy.year, hoy.month, 1)}}))

    # 2. Morosidad Total Proyectada (Plata que le deben al club)
    morosidad_total = sum(c['monto'] for c in db_cuotas.find({"estado": {"$in": ["pendiente", "vencida"]}}))

    # 3. Cobros en Efectivo registrados hoy en Sede
    efectivo_hoy = sum(c['monto'] for c in db_cuotas.find({"estado": "pagada", "metodo_pago": "Efectivo", "fecha_pago": {"$gte": datetime(hoy.year, hoy.month, hoy.day)}}))

    # 4. Porcentaje de masa societaria al día
    total_padron = db_socios.count_documents({"activo": True})
    socios_al_dia = db_socios.count_documents({"activo": True, "estado": "al_dia"})
    porcentaje_al_dia = round((socios_al_dia / total_padron) * 100, 2) if total_padron > 0 else 0
    morosos = list(db_socios.find({"estado": "mora", "activo": True}))
    
    return render_template(
        'admin/cuotas.html',
        morosos=morosos,
        recaudacion=recaudacion_mes,
        morosidad=morosidad_total,
        efectivo=efectivo_hoy,
        porcentaje=porcentaje_al_dia,
        now=hoy
    )

# Gestión de Entradas y Aforo del Estadio 
@admin.route('/entradas_panel', methods=['GET', 'POST'])
@login_required
@admin_required
def gestionar_entradas():
    db_partidos = mongo.cx['partidos']['partidos']
    db_entradas = mongo.cx['entradas']['entradas']
    
    if request.method == 'POST':
        # Botón Inhabilitar Entrada por ID de Transacción
        tx_id = request.form.get('transaction_id')
        if tx_id:
            try:
                ticket = db_entradas.find_one({"_id": ObjectId(tx_id)})
                if ticket:
                    db_entradas.update_one({"_id": ObjectId(tx_id)}, {"$set": {"estado": "anulada"}})
                    # Aca lo que hago es devolver el cupo de aforo al sector de ese partido
                    db_partidos.update_one(
                        {"_id": ticket['partido_id'], "sectores.nombre": ticket['sector']},
                        {"$inc": {"sectores.$.vendidos": -1}}
                    )
                    flash("Entrada inhabilitada y aforo liberado.", "warning")
                else:
                    flash("ID de transacción no encontrado.", "danger")
            except:
                flash("ID de transacción inválido.", "danger")
        return redirect(url_for('admin.gestionar_entradas'))

    # --- ESTADÍSTICAS EN TIEMPO REAL DESDE COMPASS ---
    partido_activo = db_partidos.find_one({"estado": "proximo"}, sort=[("fecha", 1)])
    
    recaudacion_sectores = {"Popular": 0.0, "Platea Alta": 0.0, "Preferencial": 0.0}
    total_recaudado_evento = 0.0
    sectores_partido = []
    
    if partido_activo:
        sectores_partido = partido_activo.get('sectores', [])
        for sec in sectores_partido:
            nombre = sec['nombre']
            monto_sector = sec.get('vendidos', 0) * sec.get('precio', 0.0)
            total_recaudado_evento += monto_sector
            
            if "Popular" in nombre: recaudacion_sectores["Popular"] += monto_sector
            elif "Alta" in nombre:  recaudacion_sectores["Platea Alta"] += monto_sector
            else:                   recaudacion_sectores["Preferencial"] += monto_sector

    todos_los_partidos = list(db_partidos.find().sort("fecha", 1))
    
    return render_template(
        'admin/entradas.html',
        partidos=todos_los_partidos,
        partido_actual=partido_activo,
        sectores=sectores_partido,
        recaudacion_tickets=recaudacion_sectores,
        total_recau=total_recaudado_evento
    )

@admin.route('/cuotas/generar', methods=['POST'])
@login_required
@admin_required
def generar_cuotas():
    db_cuotas = mongo.cx['cuotas']['cuotas']
    db_socios = mongo.cx['socios']['socios']
    hoy = datetime.now()

    mes   = int(request.form.get('mes'))
    anio  = int(request.form.get('anio', hoy.year))
    monto = float(request.form.get('monto'))

    dia_venc = 10
    try:
        vencimiento = datetime(anio, mes, dia_venc)
    except ValueError:
        vencimiento = datetime(anio, mes, 1)

    estado_cuota = "pendiente" if hoy <= vencimiento else "vencida"

    socios_activos = list(db_socios.find({"activo": True, "rol": "socio"}))
    creadas = 0
    for s in socios_activos:
        if not db_cuotas.find_one({"socio_id": s['_id'], "mes": mes, "anio": anio}):
            db_cuotas.insert_one({
                "socio_id": s['_id'],
                "mes": mes, "anio": anio, "monto": monto,
                "estado": estado_cuota,
                "fecha_vencimiento": vencimiento,
                "fecha_pago": None,
                "metodo_pago": None,
                "paypal_order_id": None
            })
            creadas += 1
            if estado_cuota == "vencida":
                db_socios.update_one({"_id": s['_id']}, {"$set": {"estado": "mora"}})

    flash(f"Se generaron {creadas} cuotas para {mes}/{anio}. {len(socios_activos) - creadas} socios ya tenían cuota de ese período.", "success")
    return redirect(url_for('admin.gestionar_cuotas'))


@admin.route('/sectores/actualizar/<partido_id>', methods=['POST'])
@login_required
@admin_required
def actualizar_sectores(partido_id):
    db_partidos = mongo.cx['partidos']['partidos']
    nombres    = request.form.getlist('sector_nombre')
    capacidades = request.form.getlist('sector_capacidad')
    precios    = request.form.getlist('sector_precio')
    for nombre, capacidad, precio in zip(nombres, capacidades, precios):
        db_partidos.update_one(
            {"_id": ObjectId(partido_id), "sectores.nombre": nombre},
            {"$set": {"sectores.$.capacidad": int(capacidad), "sectores.$.precio": float(precio)}}
        )
    flash("Configuración de sectores actualizada.", "success")
    return redirect(url_for('admin.gestionar_entradas'))

# RF-A03: CRUD Partidos y Cierre de Jornada
@admin.route('/partidos/nuevo', methods=['POST'])
@login_required
@admin_required
def nuevo_partido():
    nuevo = {
        "rival": request.form.get('rival'),
        "fecha": datetime.strptime(request.form.get('fecha'), '%Y-%m-%dT%H:%M'),
        "estadio": request.form.get('estadio'),
        "competencia": request.form.get('competencia'),
        "es_local": request.form.get('es_local') == 'true',
        "estado": "proximo",
        "goles_local": 0, "goles_visitante": 0,
        "sectores": [
            {"nombre": "Popular Norte", "capacidad": 12000, "vendidos": 0, "precio": 8500.0},
            {"nombre": "Platea Alta", "capacidad": 5500, "vendidos": 0, "precio": 15000.0},
            {"nombre": "Preferencial", "capacidad": 2200, "vendidos": 0, "precio": 28000.0}
        ]
    }
    mongo.cx['partidos']['partidos'].insert_one(nuevo)
    flash("Partido programado e incorporado al fixture.", "success")
    return redirect(url_for('admin.dashboard'))

@admin.route('/partidos/cierre/<partido_id>')
@login_required
@admin_required
def cierre_jornada(partido_id):
    db_partidos = mongo.cx['partidos']['partidos']
    db_socios = mongo.cx['socios']['socios']

    partido = db_partidos.find_one({"_id": ObjectId(partido_id)})
    if not partido:
        flash("Partido no encontrado.", "danger")
        return redirect(url_for('admin.dashboard'))

    sectores = partido.get('sectores', [])
    total_asistencia = sum(s.get('vendidos', 0) for s in sectores)
    recaudacion_total = sum(s.get('vendidos', 0) * s.get('precio', 0) for s in sectores)
    socios_activos = db_socios.count_documents({"activo": True, "estado": "al_dia"})

    operativo = mongo.cx['operativos']['operativos'].find_one({"partido_id": ObjectId(partido_id)})
    incidentes_medicos = operativo.get('medicos', 0) if operativo else 0
    incidentes_seguridad = operativo.get('incidentes_seg', 0) if operativo else 0

    return render_template(
        'admin/cierre_jornada.html',
        partido=partido,
        sectores=sectores,
        total_asistencia=total_asistencia,
        recaudacion_total=recaudacion_total,
        socios_activos=socios_activos,
        incidentes_medicos=incidentes_medicos,
        incidentes_seguridad=incidentes_seguridad
    )

@admin.route('/partidos/finalizar/<partido_id>', methods=['POST'])
@login_required
@admin_required
def finalizar_partido(partido_id):
    mongo.cx['partidos']['partidos'].update_one(
        {"_id": ObjectId(partido_id)},
        {"$set": {
            "estado": "finalizado",
            "goles_local": int(request.form.get('goles_local', 0)),
            "goles_visitante": int(request.form.get('goles_visitante', 0)),
            "notas_cierre": request.form.get('notas', ''),
            "fecha_cierre": datetime.now()
        }}
    )
    flash("Jornada cerrada y resultado deportivo archivado.", "success")
    return redirect(url_for('admin.dashboard'))

# RF-A06: Registro de Operativos de Seguridad
@admin.route('/operativos/<partido_id>', methods=['POST'])
@login_required
@admin_required
def guardar_operativo(partido_id):
    operativo = {
        "partido_id": ObjectId(partido_id),
        "policias": int(request.form.get('policias', 0)),
        "seguridad_privada": int(request.form.get('seguridad_privada', 0)),
        "stewards": int(request.form.get('stewards', 0)),
        "observaciones": request.form.get('observaciones')
    }
    mongo.cx['operativos']['operativos'].update_many({"partido_id": ObjectId(partido_id)}, {"$set": operativo}, upsert=True)
    flash("Personal de seguridad y operativo de control guardado.", "success")
    return redirect(url_for('admin.dashboard'))