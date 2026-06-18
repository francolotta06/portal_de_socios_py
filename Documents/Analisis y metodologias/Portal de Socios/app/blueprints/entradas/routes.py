from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask_login import login_required, current_user
from app import mongo
from app.paypal_helper import crear_orden, capturar_orden
from bson.objectid import ObjectId
from datetime import datetime
import uuid

entradas = Blueprint('entradas', __name__, url_prefix='/entradas')


@entradas.route('/')
@login_required
def index():
    socio = mongo.cx['socios']['socios'].find_one({"_id": ObjectId(current_user.id)})
    partidos = list(mongo.cx['partidos']['partidos'].find({"estado": "proximo"}).sort("fecha", 1))
    mis_entradas = list(mongo.cx['entradas']['entradas'].find(
        {"socio_id": ObjectId(current_user.id)}
    ).sort("fecha_compra", -1).limit(5))
    return render_template('entradas/index.html', partidos=partidos, socio=socio, entradas=mis_entradas)


@entradas.route('/historial')
@login_required
def historial():
    socio = mongo.cx['socios']['socios'].find_one({"_id": ObjectId(current_user.id)})
    mis_entradas = list(mongo.cx['entradas']['entradas'].find(
        {"socio_id": ObjectId(current_user.id)}
    ).sort("fecha_compra", -1))
    return render_template('entradas/historial.html', entradas=mis_entradas, socio=socio)


@entradas.route('/comprar/<partido_id>', methods=['GET'])
@login_required
def comprar(partido_id):
    partido = mongo.cx['partidos']['partidos'].find_one({"_id": ObjectId(partido_id)})
    if not partido:
        flash("El partido solicitado no se encuentra disponible.", "danger")
        return redirect(url_for('entradas.index'))

    socio_data = mongo.cx['socios']['socios'].find_one({"_id": ObjectId(current_user.id)})
    if socio_data.get('estado') == 'mora':
        flash("Debés regularizar tus cuotas sociales para adquirir entradas.", "danger")
        return redirect(url_for('cuotas.mis_cuotas'))

    descuento = 0.30 if socio_data.get('estado') == 'al_dia' else 0.0
    return render_template('entradas/comprar.html', partido=partido, socio=socio_data, descuento=descuento)


@entradas.route('/iniciar-pago', methods=['POST'])
@login_required
def iniciar_pago():
    partido_id = request.form.get('partido_id')
    sector_nombre = request.form.get('sector_nombre')

    partido = mongo.cx['partidos']['partidos'].find_one({"_id": ObjectId(partido_id)})
    if not partido:
        flash("Partido no encontrado.", "danger")
        return redirect(url_for('socios.perfil'))

    # RF: máximo 2 entradas por socio por partido
    ya_compradas = mongo.cx['entradas']['entradas'].count_documents({
        "socio_id": ObjectId(current_user.id),
        "partido_id": ObjectId(partido_id),
        "estado": "valido"
    })
    if ya_compradas >= 2:
        flash("Ya tenés el máximo de 2 entradas permitidas para este partido.", "warning")
        return redirect(url_for('entradas.comprar', partido_id=partido_id))

    sector_elegido = next(
        (s for s in partido.get('sectores', []) if s['nombre'] == sector_nombre),
        None
    )
    if not sector_elegido:
        flash("Sector no válido.", "danger")
        return redirect(url_for('entradas.comprar', partido_id=partido_id))

    if sector_elegido['vendidos'] >= sector_elegido['capacidad']:
        flash(f"Localidades agotadas para el sector {sector_nombre}.", "danger")
        return redirect(url_for('entradas.comprar', partido_id=partido_id))

    socio_pago = mongo.cx['socios']['socios'].find_one({"_id": ObjectId(current_user.id)})
    descuento = 0.30 if socio_pago.get('estado') == 'al_dia' else 0.0
    precio_final = round(sector_elegido['precio'] * (1 - descuento), 2)

    session['pago_partido_id'] = partido_id
    session['pago_sector_nombre'] = sector_nombre
    session['pago_precio_final'] = precio_final

    descripcion = f"Entrada {partido['rival']} - {sector_nombre}"
    try:
        order_id, url_aprobacion = crear_orden(
            monto_ars=precio_final,
            url_retorno=url_for('entradas.pago_exitoso', _external=True),
            url_cancelacion=url_for('entradas.pago_cancelado', _external=True),
            descripcion=descripcion
        )
        session['pago_orden_id'] = order_id
        return redirect(url_aprobacion)
    except Exception as e:
        flash(f"Error al conectar con PayPal: {e}", "danger")
        return redirect(url_for('entradas.comprar', partido_id=partido_id))


@entradas.route('/pago-exitoso')
@login_required
def pago_exitoso():
    order_id = request.args.get('token')
    if not order_id:
        flash("Token de pago inválido.", "danger")
        return redirect(url_for('socios.perfil'))

    partido_id   = session.pop('pago_partido_id', None)
    sector_nombre = session.pop('pago_sector_nombre', None)
    precio_final  = session.pop('pago_precio_final', None)
    session.pop('pago_orden_id', None)

    if not partido_id or not sector_nombre:
        flash("No se encontraron datos del pago. Si ya pagaste, contactá al club.", "warning")
        return redirect(url_for('socios.perfil'))

    try:
        resultado = capturar_orden(order_id)
        if resultado.get('status') != 'COMPLETED':
            flash("El pago no fue completado por PayPal. Intentá nuevamente.", "danger")
            return redirect(url_for('entradas.comprar', partido_id=partido_id))
    except Exception as e:
        flash(f"Error al confirmar el pago con PayPal: {e}", "danger")
        return redirect(url_for('entradas.comprar', partido_id=partido_id))

    partido = mongo.cx['partidos']['partidos'].find_one({"_id": ObjectId(partido_id)})
    sector_elegido = next(
        (s for s in partido.get('sectores', []) if s['nombre'] == sector_nombre),
        None
    )

    mongo.cx['partidos']['partidos'].update_one(
        {"_id": ObjectId(partido_id), "sectores.nombre": sector_nombre},
        {"$inc": {"sectores.$.vendidos": 1}}
    )

    nuevo_ticket = {
        "socio_id": ObjectId(current_user.id),
        "partido_id": ObjectId(partido_id),
        "rival": partido['rival'],
        "competencia": partido['competencia'],
        "fecha_partido": partido['fecha'],
        "sector": sector_nombre,
        "precio_pagado": precio_final if precio_final is not None else sector_elegido['precio'],
        "precio_base": sector_elegido['precio'],
        "fecha_compra": datetime.now(),
        "codigo_qr_token": str(uuid.uuid4()),
        "paypal_order_id": order_id,
        "estado": "valido"
    }
    resultado_insert = mongo.cx['entradas']['entradas'].insert_one(nuevo_ticket)

    flash(f"¡Pago confirmado! Tu entrada para {partido['rival']} fue generada.", "success")
    return redirect(url_for('entradas.ver_entrada', ticket_id=str(resultado_insert.inserted_id)))


@entradas.route('/pago-cancelado')
@login_required
def pago_cancelado():
    partido_id = session.pop('pago_partido_id', None)
    session.pop('pago_sector_nombre', None)
    session.pop('pago_orden_id', None)
    flash("Cancelaste el pago. Tu lugar no fue reservado.", "warning")
    if partido_id:
        return redirect(url_for('entradas.comprar', partido_id=partido_id))
    return redirect(url_for('socios.perfil'))


@entradas.route('/entrada/<ticket_id>')
@login_required
def ver_entrada(ticket_id):
    ticket = mongo.cx['entradas']['entradas'].find_one({
        "_id": ObjectId(ticket_id),
        "socio_id": ObjectId(current_user.id)
    })
    if not ticket:
        flash("Entrada no encontrada.", "danger")
        return redirect(url_for('entradas.historial'))
    socio = mongo.cx['socios']['socios'].find_one({"_id": ObjectId(current_user.id)})
    return render_template('entradas/entrada_digital.html', ticket=ticket, socio=socio)