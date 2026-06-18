from flask import Blueprint, render_template, request, redirect, url_for, flash, session
from flask_login import login_required, current_user
from app import mongo
from app.paypal_helper import crear_orden, capturar_orden
from bson.objectid import ObjectId
from datetime import datetime

cuotas = Blueprint('cuotas', __name__, url_prefix='/cuotas')


@cuotas.route('/mis-cuotas')
@login_required
def mis_cuotas():
    lista_cuotas = list(mongo.cx['cuotas']['cuotas'].find(
        {"socio_id": ObjectId(current_user.id)}
    ).sort([("anio", -1), ("mes", -1)]))
    socio = mongo.cx['socios']['socios'].find_one({"_id": ObjectId(current_user.id)})
    pendientes = [c for c in lista_cuotas if c['estado'] != 'pagada']
    pagadas    = [c for c in lista_cuotas if c['estado'] == 'pagada']
    cuota_mensual = pendientes[0]['monto'] if pendientes else (pagadas[0]['monto'] if pagadas else 0)
    return render_template('cuotas/historial.html',
                           cuotas=lista_cuotas,
                           socio=socio,
                           pendientes=pendientes,
                           pagadas=pagadas,
                           cuota_mensual=cuota_mensual)


@cuotas.route('/simulacion', methods=['GET'])
@login_required
def simulacion_pago():
    ids = request.args.getlist('cuota_ids')
    if not ids:
        flash("Seleccioná al menos una cuota para pagar.", "warning")
        return redirect(url_for('cuotas.mis_cuotas'))

    socio = mongo.cx['socios']['socios'].find_one({"_id": ObjectId(current_user.id)})
    cuotas_db = list(mongo.cx['cuotas']['cuotas'].find(
        {"_id": {"$in": [ObjectId(i) for i in ids]}}
    ))

    subtotal = sum(c['monto'] for c in cuotas_db)
    recargo = subtotal * 0.10 if socio['estado'] == 'mora' else 0.0
    gastos_fijos = 250.0
    total = subtotal + recargo + gastos_fijos

    return render_template('cuotas/pagos.html',
                           ids_a_pagar=ids,
                           cantidad_cuotas=len(cuotas_db),
                           subtotal=subtotal,
                           recargo_mora=recargo,
                           total_final=total)


@cuotas.route('/iniciar-pago', methods=['POST'])
@login_required
def iniciar_pago():
    ids = request.form.getlist('cuotas_a_liquidar')
    if not ids:
        flash("No se recibieron cuotas para pagar.", "warning")
        return redirect(url_for('cuotas.mis_cuotas'))

    socio = mongo.cx['socios']['socios'].find_one({"_id": ObjectId(current_user.id)})
    cuotas_db = list(mongo.cx['cuotas']['cuotas'].find(
        {"_id": {"$in": [ObjectId(i) for i in ids]}}
    ))

    subtotal = sum(c['monto'] for c in cuotas_db)
    recargo = subtotal * 0.10 if socio['estado'] == 'mora' else 0.0
    total = subtotal + recargo + 250.0

    session['cuotas_pendientes'] = ids
    descripcion = f"Cuotas sociales ({len(ids)} periodo/s) - Club Atletico"

    try:
        order_id, url_aprobacion = crear_orden(
            monto_ars=total,
            url_retorno=url_for('cuotas.pago_exitoso', _external=True),
            url_cancelacion=url_for('cuotas.pago_cancelado', _external=True),
            descripcion=descripcion
        )
        session['cuotas_orden_id'] = order_id
        return redirect(url_aprobacion)
    except Exception as e:
        flash(f"Error al conectar con PayPal: {e}", "danger")
        return redirect(url_for('cuotas.mis_cuotas'))


@cuotas.route('/pago-exitoso')
@login_required
def pago_exitoso():
    order_id = request.args.get('token')
    if not order_id:
        flash("Token de pago inválido.", "danger")
        return redirect(url_for('cuotas.mis_cuotas'))

    ids = session.pop('cuotas_pendientes', [])
    session.pop('cuotas_orden_id', None)

    if not ids:
        flash("No se encontraron cuotas pendientes. Si ya pagaste, contactá al club.", "warning")
        return redirect(url_for('cuotas.mis_cuotas'))

    try:
        resultado = capturar_orden(order_id)
        if resultado.get('status') != 'COMPLETED':
            flash("El pago no fue completado por PayPal. Intentá nuevamente.", "danger")
            return redirect(url_for('cuotas.mis_cuotas'))
    except Exception as e:
        flash(f"Error al confirmar el pago con PayPal: {e}", "danger")
        return redirect(url_for('cuotas.mis_cuotas'))

    mongo.cx['cuotas']['cuotas'].update_many(
        {"_id": {"$in": [ObjectId(i) for i in ids]}, "socio_id": ObjectId(current_user.id)},
        {"$set": {
            "estado": "pagada",
            "fecha_pago": datetime.now(),
            "metodo_pago": "PayPal",
            "paypal_order_id": order_id
        }}
    )

    deuda_restante = mongo.cx['cuotas']['cuotas'].find_one({
        "socio_id": ObjectId(current_user.id),
        "estado": {"$in": ["pendiente", "vencida"]}
    })
    nuevo_estado = "al_dia" if not deuda_restante else "mora"
    mongo.cx['socios']['socios'].update_one(
        {"_id": ObjectId(current_user.id)},
        {"$set": {"estado": nuevo_estado}}
    )

    flash("¡Pago confirmado con PayPal! Tus cuotas fueron acreditadas.", "success")
    return redirect(url_for('cuotas.mis_cuotas'))


@cuotas.route('/pago-cancelado')
@login_required
def pago_cancelado():
    session.pop('cuotas_pendientes', None)
    session.pop('cuotas_orden_id', None)
    flash("Cancelaste el pago. Tus cuotas siguen pendientes.", "warning")
    return redirect(url_for('cuotas.mis_cuotas'))


@cuotas.route('/recibo/<cuota_id>')
@login_required
def recibo(cuota_id):
    cuota = mongo.cx['cuotas']['cuotas'].find_one({
        "_id": ObjectId(cuota_id),
        "socio_id": ObjectId(current_user.id),
        "estado": "pagada"
    })
    if not cuota:
        flash("Recibo no encontrado.", "danger")
        return redirect(url_for('cuotas.mis_cuotas'))
    socio = mongo.cx['socios']['socios'].find_one({"_id": ObjectId(current_user.id)})
    return render_template('cuotas/recibo.html', cuota=cuota, socio=socio)
