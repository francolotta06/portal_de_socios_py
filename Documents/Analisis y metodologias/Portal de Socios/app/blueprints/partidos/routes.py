from flask import Blueprint, render_template, request
from app import mongo

partidos = Blueprint('partidos', __name__, url_prefix='/partidos')

@partidos.route('/fixture')
def fixture():
    lista_partidos = list(mongo.db.partidos.find().sort("fecha", 1))
    return render_template('partidos/fixture.html', partidos=lista_partidos)