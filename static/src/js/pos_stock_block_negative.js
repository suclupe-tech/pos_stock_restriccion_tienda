/** @odoo-module **/

import { patch } from "@web/core/utils/patch";
import { ProductTemplate } from "@point_of_sale/app/models/product_template";

console.log("PATCH PRODUCT TEMPLATE SIN STOCK CARGADO");

patch(ProductTemplate.prototype, {
    get canBeDisplayed() {
        if ((this.qty_available || 0) <= 0) {
            return false;
        }
        return true;
    },
});