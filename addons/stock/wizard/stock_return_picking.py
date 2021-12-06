# -*- coding: utf-8 -*-
##############################################################################
#
#    OpenERP, Open Source Management Solution
#    Copyright (C) 2004-2010 Tiny SPRL (<http://tiny.be>).
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

from openerp.osv import osv, fields
from openerp.tools.translate import _
import openerp.addons.decimal_precision as dp
from openerp.exceptions import UserError
from openerp import SUPERUSER_ID

class stock_return_picking_line(osv.osv_memory):
    _name = "stock.return.picking.line"
    _rec_name = 'product_id'

    _columns = {
        'product_id': fields.many2one('product.product', string="Product", required=True),
        'quantity': fields.float("Quantity", digits_compute=dp.get_precision('Product Unit of Measure'), required=True),
        'wizard_id': fields.many2one('stock.return.picking', string="Wizard"),
        'move_id': fields.many2one('stock.move', "Move"),
        'lot_id': fields.many2one('stock.production.lot', 'Serial Number', help="Used to choose the lot/serial number of the product returned"),
    }


class stock_return_picking(osv.osv_memory):
    _name = 'stock.return.picking'
    _description = 'Return Picking'
    _columns = {
        'product_return_moves': fields.one2many('stock.return.picking.line', 'wizard_id', 'Moves'),
        'move_dest_exists': fields.boolean('Chained Move Exists', readonly=True, help="Technical field used to hide help tooltip if not needed"),
    }

    def default_get(self, cr, uid, fields, context=None):
        """
         To get default values for the object.
         @param self: The object pointer.
         @param cr: A database cursor
         @param uid: ID of the user currently logged in
         @param fields: List of fields for which we want default values
         @param context: A standard dictionary
         @return: A dictionary with default values for all field in ``fields``
        """
        result1 = []
        if context is None:
            context = {}
        if context and context.get('active_ids', False):
            if len(context.get('active_ids')) > 1:
                raise osv.except_osv(_('Warning!'), _("You may only return one picking at a time!"))
        res = super(stock_return_picking, self).default_get(cr, uid, fields, context=context)
        record_id = context and context.get('active_id', False) or False
        uom_obj = self.pool.get('product.uom')
        pick_obj = self.pool.get('stock.picking')
        pick = pick_obj.browse(cr, uid, record_id, context=context)
        quant_obj = self.pool.get("stock.quant")
        chained_move_exist = False
        if pick:
            if pick.state != 'done':
                raise UserError(_("You may only return pickings that are Done!"))

            quants_devueltos = []
            if pick.wave_id:
                cr.execute('''
                    SELECT
                        quant.ID
                    FROM
                        stock_picking_wave remito
                        LEFT JOIN stock_picking devolucion ON devolucion.wave_id = remito.ID
                        LEFT JOIN stock_move MOVE ON MOVE.picking_id = devolucion.ID
                        LEFT JOIN stock_quant_move_rel quant_x_move ON quant_x_move.move_id = MOVE.ID
                        LEFT JOIN stock_quant quant ON quant.ID = quant_x_move.quant_id
                        LEFT JOIN stock_picking_type picking_type ON picking_type.ID = devolucion.picking_type_id
                    WHERE
                        picking_type.code = 'incoming'
                        AND remito.ID = %s
                        ''', [pick.wave_id.id])
                quants_devueltos = [r[0] for r in cr.fetchall()]

            for move in pick.move_lines:
                if move.state == 'cancel':
                    continue
                lote_result_ids = []
                if move.move_dest_id:
                    chained_move_exist = True
                #Sum the quants in that location that can be returned (they should have been moved by the moves that were included in the returned picking)
                qty = 0
                quant_search = False
                validar_trazabilidad = True
                tracking = move.product_id.tracking
                if 'validar_trazabilidad' in move.product_id.categ_id:
                    validar_trazabilidad = move.product_id.categ_id.validar_trazabilidad
                # Lote Indivisible y Serie siempre validan Trazabilidad (sólo los Quants originales)
                if validar_trazabilidad or tracking in ['lote_indivisible', 'serial']:
                    quant_search = quant_obj.search(cr, uid, [('history_ids', 'in', move.id), ('id', 'not in', quants_devueltos), ('qty', '>', 0.0), ('location_id', 'child_of', move.location_dest_id.id)], context=context)
                # Lote permite no validar Trazabilidad, pero los posibles quants igual quedan atados a los Lotes que se recibieron originalmente (cualquier Quant pero de los Lotes originales)
                elif tracking == 'lot':
                    lote_ids = list(set([q.lot_id.id for q in move.quant_ids]))
                    quant_search = quant_obj.search(cr, uid, [('product_id', '=', move.product_id.id), ('lot_id', 'in', lote_ids), ('qty', '>', 0.0), ('location_id', 'child_of', move.location_dest_id.id)], context=context)
                    # Dict con {lote_id: cant} donde se acumula la cantidad original que se recibió/envió en cada Lote, ya que en un Move se pueden recibir varios lotes, 
                    # por lo que el move.product_qty no nos sirve para saber la cantidad original, y así no permitir devolver más cantidad de la original
                    lote_cantidad = {}
                    quant_original_ids = quant_obj.search(cr, uid, [('history_ids', 'in', move.id), ('qty', '>', 0.0)], context=context)
                    quant_originales = quant_obj.browse(cr, SUPERUSER_ID, quant_original_ids, context=context)
                    for q in quant_originales:
                        if q.lot_id.id not in lote_cantidad:
                            lote_cantidad[q.lot_id.id] = q.qty
                        else:
                            lote_cantidad[q.lot_id.id] += q.qty
                        q.lot_id.id
                # Sin Tracking permite no validar Trazabilidad (cualquier Quant)
                else:
                    # Se suda porque puede ser que no tengo stock de quants de su sucursal en la ubicacion de clientes y como no se valida trazabilidad no importa
                    quant_search = quant_obj.search(cr, SUPERUSER_ID, [('product_id', '=', move.product_id.id), ('qty', '>', 0.0), ('location_id', 'child_of', move.location_dest_id.id)], context=context)
                for quant in quant_obj.browse(cr, SUPERUSER_ID, quant_search, context=context):
                    lote = quant.lot_id
                    cantidad = quant.qty
                    if not quant.reservation_id or quant.reservation_id.origin_returned_move_id.id != move.id:
                        if lote and tracking in ['lote_indivisible', 'serial']:
                            result1.append({'product_id': move.product_id.id, 'quantity': cantidad, 'move_id': move.id, 'lot_id': lote.id})
                        elif lote and tracking == 'lot':
                            if lote.id not in lote_result_ids:
                                lote_result_ids.append(lote.id)
                                if cantidad > lote_cantidad.get(lote.id, 0.0):
                                    cantidad = lote_cantidad.get(lote.id, 0.0)
                                result1.append({'product_id': move.product_id.id, 'quantity': cantidad, 'move_id': move.id, 'lot_id': lote.id})
                            else:
                                for linea in result1:
                                    if lote.id in linea.values():
                                        linea['quantity'] += cantidad
                                        if linea['quantity'] > lote_cantidad.get(lote.id, 0.0):
                                            linea['quantity'] = lote_cantidad.get(lote.id, 0.0)
                                        break
                        else:
                            qty += cantidad
                qty = uom_obj._compute_qty(cr, uid, move.product_id.uom_id.id, qty, move.product_uom.id)
                if not validar_trazabilidad and tracking == 'none':
                    cantidad_restante = move.product_qty - move.cantidad_devuelta
                    # Devolución de Compra
                    if pick.picking_type_id.return_picking_type_id.code == 'outgoing':
                        qty = cantidad_restante
                    # Devolución de Venta
                    elif pick.picking_type_id.return_picking_type_id.code == 'incoming' and qty > cantidad_restante:
                        qty = cantidad_restante
                if qty:
                    result1.append({'product_id': move.product_id.id, 'quantity': qty, 'move_id': move.id})

            if len(result1) == 0:
                raise UserError(_("No products to return (only lines in Done state and not fully returned yet can be returned)!"))
            if 'product_return_moves' in fields:
                res.update({'product_return_moves': result1})
            if 'move_dest_exists' in fields:
                res.update({'move_dest_exists': chained_move_exist})
        return res

    def _create_returns(self, cr, uid, ids, context=None):
        if context is None:
            context = {}
        record_id = context and context.get('active_id', False) or False
        move_obj = self.pool.get('stock.move')
        pick_obj = self.pool.get('stock.picking')
        uom_obj = self.pool.get('product.uom')
        data_obj = self.pool.get('stock.return.picking.line')
        pick = pick_obj.browse(cr, uid, record_id, context=context)
        data = self.read(cr, uid, ids[0], context=context)
        returned_lines = 0

        # Cancel assignment of existing chained assigned moves
        moves_to_unreserve = []
        for move in pick.move_lines:
            to_check_moves = [move.move_dest_id] if move.move_dest_id.id else []
            while to_check_moves:
                current_move = to_check_moves.pop()
                if current_move.state not in ('done', 'cancel') and current_move.reserved_quant_ids:
                    moves_to_unreserve.append(current_move.id)
                split_move_ids = move_obj.search(cr, uid, [('split_from', '=', current_move.id)], context=context)
                if split_move_ids:
                    to_check_moves += move_obj.browse(cr, uid, split_move_ids, context=context)

        if moves_to_unreserve:
            move_obj.do_unreserve(cr, uid, moves_to_unreserve, context=context)
            #break the link between moves in order to be able to fix them later if needed
            move_obj.write(cr, uid, moves_to_unreserve, {'move_orig_ids': False}, context=context)

        #Create new picking for returned products
        pick_type_id = pick.picking_type_id.return_picking_type_id and pick.picking_type_id.return_picking_type_id.id or pick.picking_type_id.id
        new_picking = pick_obj.copy(cr, uid, pick.id, {
            'move_lines': [],
            'picking_type_id': pick_type_id,
            'state': 'draft',
            'origin': pick.name,
        }, context=context)

        for data_get in data_obj.browse(cr, uid, data['product_return_moves'], context=context):
            move = data_get.move_id
            if not move:
                raise UserError(_("You have manually created product lines, please delete them to proceed"))
            new_qty = data_get.quantity
            if new_qty:
                # The return of a return should be linked with the original's destination move if it was not cancelled
                if move.origin_returned_move_id.move_dest_id.id and move.origin_returned_move_id.move_dest_id.state != 'cancel':
                    move_dest_id = move.origin_returned_move_id.move_dest_id.id
                else:
                    move_dest_id = False
                    
                location_id = context.get('force_location_id') or move.location_dest_id.id
                
                returned_lines += 1
                move_obj.copy(cr, uid, move.id, {
                    'product_id': data_get.product_id.id,
                    'product_uom_qty': new_qty,
                    'product_uos_qty': new_qty * move.product_uos_qty / move.product_uom_qty,
                    'picking_id': new_picking,
                    'state': 'draft',
                    'location_id': location_id,
                    'location_dest_id': move.location_id.id,
                    'picking_type_id': pick_type_id,
                    'warehouse_id': pick.picking_type_id.warehouse_id.id,
                    'origin_returned_move_id': move.id,
                    'procure_method': 'make_to_stock',
                    'restrict_lot_id': data_get.lot_id.id,
                    'move_dest_id': move_dest_id,
                    'devolucion_no_validar_trazabilidad': 'validar_trazabilidad' in data_get.product_id.categ_id and not data_get.product_id.categ_id.validar_trazabilidad and move.product_id.tracking in ['lot', 'none'],
                })

        if not returned_lines:
            raise UserError(_("Please specify at least one non-zero quantity."))

        pick_obj.action_confirm(cr, uid, [new_picking], context=context)
        pick_obj.action_assign(cr, uid, [new_picking], context)
        return new_picking, pick_type_id

    def create_returns(self, cr, uid, ids, context=None):
        """
         Creates return picking.
         @param self: The object pointer.
         @param cr: A database cursor
         @param uid: ID of the user currently logged in
         @param ids: List of ids selected
         @param context: A standard dictionary
         @return: A dictionary which of fields with values.
        """
        new_picking_id, pick_type_id = self._create_returns(cr, uid, ids, context=context)
        # Override the context to disable all the potential filters that could have been set previously
        ctx = {
            'search_default_picking_type_id': pick_type_id,
            'search_default_draft': False,
            'search_default_assigned': False,
            'search_default_confirmed': False,
            'search_default_ready': False,
            'search_default_late': False,
            'search_default_available': False,
        }
        return {
            'domain': "[('id', 'in', [" + str(new_picking_id) + "])]",
            'name': _('Returned Picking'),
            'view_type': 'form',
            'view_mode': 'tree,form',
            'res_model': 'stock.picking',
            'type': 'ir.actions.act_window',
            'context': ctx,
        }
