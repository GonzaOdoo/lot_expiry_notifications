from odoo import models, api, fields
from odoo.exceptions import ValidationError
from datetime import timedelta
import base64
import pytz
from datetime import datetime
import logging

_logger = logging.getLogger(__name__)

class ReporteSemanalLotes(models.Model):
    _name = 'report.weekly.lots'
    _description = 'Reporte Semanal de Lotes Próximos a Vencer'

    name = fields.Char(string="Nombre", default="Configuración de Reporte de Lotes")
    days_threshold = fields.Integer(
        string="Días hasta vencimiento",
        default=30,
        help="Productos cuyo lote vence en menos de X días serán incluidos."
    )
    category_ids = fields.Many2many(
        'product.category',
        string="Categorías a incluir",
        help="Dejar vacío para incluir todas las categorías."
    )

    @api.model
    def _get_singleton(self):
        """Devuelve el único registro; lo crea si no existe."""
        record = self.search([], limit=1)
        if not record:
            record = self.create({
                'name': 'Configuración de Reporte de Lotes'
            })
        return record

    @api.constrains('id')
    def _check_singleton(self):
        """Evita crear más de un registro."""
        if self.search_count([]) > 1:
            raise ValidationError("Solo puede existir un registro de configuración para este reporte.")
            
    def action_generate_report(self):
        self.ensure_one()
        quants = self._get_expiring_quants()
        if not quants:
            raise ValidationError("No se encontraron lotes próximos a vencer.")
    
        # Obtener vencidos
        expired_quants = self._get_expired_quants(self.category_ids.ids)
        expired_data = []
        for q in expired_quants:
            expired_data.append({
                'product_name': q.product_id.display_name or '',
                'category_name': q.product_id.categ_id.display_name or 'Sin categoría',
                'lot_name': q.lot_id.name or '',
                'in_date': q.in_date.strftime('%d/%m/%Y') if q.in_date else '',
                'expiration_date': q.lot_id.expiration_date.strftime('%d/%m/%Y') if q.lot_id.expiration_date else '',
                'location_name': q.location_id.name or '',
                'quantity': q.quantity,
            })
    
        report_generation_date = self._get_current_user_datetime_str()
    
        # ✅ PASAR TODO EN EL CONTEXTO
        return self.env.ref('lot_expiry_notifications.report_weekly_lots_pdf').with_context(
            report_generation_date=report_generation_date,
            expired_quants=expired_data,
            days_threshold=self.days_threshold
        ).report_action(quants.ids)

    def _get_expiring_quants(self):
        """Obtiene los quant (lotes) próximos a vencer (no incluye vencidos), ordenados por fecha de vencimiento ascendente."""
        self.ensure_one()
        today = fields.Date.today()
        date_limit = today + timedelta(days=self.days_threshold)
        domain = [
            ('lot_id.expiration_date', '!=', False),
            ('lot_id.expiration_date', '>=', today),
            ('lot_id.expiration_date', '<=', date_limit),
            ('quantity', '>', 0),
            ('location_id.usage', '=', 'internal'),
        ]
        if self.category_ids:
            domain += [('product_id.categ_id', 'in', self.category_ids.ids)]
        
        # Ordenar por fecha de vencimiento: los más próximos primero
        return self.env['stock.quant'].search(domain, order='expiration_date')

    def _get_expired_quants(self, category_ids=None):
        """Obtiene lotes ya vencidos (fecha < hoy), cantidad > 0, ubicación interna."""
        today = fields.Date.today()
        domain = [
            ('lot_id.expiration_date', '!=', False),
            ('lot_id.expiration_date', '<', today),
            ('quantity', '>', 0),
            ('location_id.usage', '=', 'internal'),
        ]
        if category_ids:
            domain += [('product_id.categ_id', 'in', category_ids)]
        return self.env['stock.quant'].search(domain, order='expiration_date')
            
 
    def action_send_email_by_category(self):
        """Envía un correo por cada categoría con su respectivo PDF."""
        self.ensure_one()
        quants = self._get_expiring_quants()
        if not quants:
            _logger.info("No hay lotes próximos a vencer.")
            return

        # Agrupar por categoría
        grouped = {}
        for quant in quants:
            categ = quant.product_id.categ_id or self.env.ref('product.product_category_all')
            grouped.setdefault(categ, self.env['stock.quant'])
            grouped[categ] |= quant

        template = self.env.ref('tu_modulo.email_template_expiring_lots')
        for category, quants_in_categ in grouped.items():
            self._send_email_with_pdf(template, category, quants_in_categ)

    def _send_email_with_pdf(self, template, category, quants):
        """Envía un correo con el PDF adjunto para una categoría dada."""
        report = self.env.ref('tu_modulo.report_weekly_lots_pdf')
        pdf_content, _ = report._render_qweb_pdf(quants.ids)
        filename = f"Lotes_a_vencer_{category.name.replace('/', '_')}_{fields.Date.today()}.pdf"

        attachment = self.env['ir.attachment'].create({
            'name': filename,
            'type': 'binary',
            'datas': base64.b64encode(pdf_content),
            'mimetype': 'application/pdf',
        })

        email_values = {
            'email_to': self.env.user.email,
            'attachment_ids': [(6, 0, [attachment.id])],
            'subject': f"⚠️ Lotes próximos a vencer - {category.name}",
        }

        template.send_mail(
            self.id,
            email_values=email_values,
            force_send=True
        )

    def send_expiring_lots_report_by_category(self):
        config = self._get_singleton()
        recipients = self.env['report.weekly.lots.recipient'].search([])
        
        for rule in recipients:
            # Filtrar quants solo para las categorías de esta regla
            domain = [
                ('lot_id.expiration_date', '>=', fields.Date.today()),
                ('lot_id.expiration_date', '<=', fields.Date.today() + timedelta(days=config.days_threshold)),
                ('quantity', '>', 0),
                ('location_id.usage', '=', 'internal'),
                ('product_id.categ_id', 'in', rule.category_ids.ids),
            ]
            quants = self.env['stock.quant'].search(domain, order='expiration_date')
            expired_quants = self._get_expired_quants(rule.category_ids.ids)

            # Convertir expired_quants a datos serializables
            expired_data = []
            for q in expired_quants:
                expired_data.append({
                    'product_name': q.product_id.display_name or '',
                    'category_name': q.product_id.categ_id.display_name or 'Sin categoría',
                    'lot_name': q.lot_id.name or '',
                    'in_date': q.in_date.strftime('%d/%m/%Y') if q.in_date else '',
                    'expiration_date': q.lot_id.expiration_date.strftime('%d/%m/%Y') if q.lot_id.expiration_date else '',
                    'location_name': q.location_id.name or '',
                    'quantity': q.quantity,
                })
            # Preparar destinatarios
            emails = set()
            emails.update(rule.user_ids.filtered('email').mapped('email'))
            emails.update(rule.partner_ids.filtered('email').mapped('email'))
            if not emails:
                continue
    
            subject = f"Reporte Semanal de Lotes Próximos a Vencer - {', '.join(rule.category_ids.mapped('name'))}"
            
            if quants or expired_quants:
                # ✅ Hay lotes → generar PDF y adjuntar
                report_name = 'lot_expiry_notifications.report_weekly_lots_pdf'
                pdf_content, _ = self.env['ir.actions.report']._render_qweb_pdf(report_name, quants.ids,data={'expired_quants': expired_data,'days':self.days_threshold})
                attachment_vals = [{
                    'name': 'reporte_lotes_vencimiento.pdf',
                    'type': 'binary',
                    'datas': base64.b64encode(pdf_content).decode('utf-8'),
                    'mimetype': 'application/pdf'
                }]
                body = "<p>Adjunto el reporte de lotes próximos a vencer.</p>"
            else:
                # ❌ No hay lotes → sin adjunto, mensaje informativo
                attachment_vals = []
                body = f"<p>No se encontraron lotes próximos a vencer o vencidos en las categorías asignadas en los próximos {self.days_threshold} días.</p>"
    
            mail_values = {
                'subject': subject,
                'body_html': body,
                'email_to': ','.join(emails),
            }
            if attachment_vals:
                mail_values['attachment_ids'] = [(0, 0, att) for att in attachment_vals]
    
            self.env['mail.mail'].create(mail_values).send()

    def _get_current_user_datetime_str(self):
        """Devuelve la fecha y hora actual en la zona horaria del usuario, como string."""
        tz = self.env.user.tz or 'UTC'
        user_tz = pytz.timezone(tz)
        now_user = datetime.now(user_tz)
        return now_user.strftime('%d/%m/%Y %H:%M')


class ReportWeeklyLotsRecipient(models.Model):
    _name = 'report.weekly.lots.recipient'
    _description = 'Destinatarios del Reporte Semanal por Categoría'

    name = fields.Char(string="Descripción", compute='_compute_name', store=True)
    category_ids = fields.Many2many(
        'product.category',
        string="Categorías",
        required=True,
        help="Reporte para estas categorías será enviado a los destinatarios indicados."
    )
    user_ids = fields.Many2many(
        'res.users',
        string="Usuarios Internos"
    )
    partner_ids = fields.Many2many(
        'res.partner',
        string="Contactos Externos",
        domain=[('email', '!=', False)]
    )

    @api.depends('category_ids')
    def _compute_name(self):
        for rec in self:
            cats = ", ".join(rec.category_ids.mapped('name')[:3])
            rec.name = f"Destinatarios para: {cats}" if cats else "Sin categorías"