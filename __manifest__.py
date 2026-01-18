# -*- coding: utf-8 -*-
{
    "name": "Lotes expirados recordatorio",
    "version": "18.0.1.0.0",
    "category": "Tools",
    "summary": "Modulo para enviar recordatorios de lotes expirados",
    "description": "Modulo para enviar recordatorios de lotes expirados",
    "author": 'GonzaOdoo',
    "maintainer": "GonzaOdoo",
    "website": 'https://www.yourcompany.com',
    "depends": ['stock','product_expiry'],
    "assets": {},
    "data":[
        'security/ir.model.access.csv',
        #'views/mail_template.xml',
        'views/report_lots.xml',
         'views/report_views.xml',
    ],
    "license": "LGPL-3",
    "installable": True,
    "auto_install": False,
    "application": True
}