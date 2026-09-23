/** @odoo-module **/

import { Component, onWillStart, useState } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";

export class VariantDistributionAction extends Component {
    static template =
        "pos_stock_restriccion_tienda.VariantDistributionAction";

    setup() {
        this.orm = useService("orm");
        this.notification = useService("notification");

        this.state = useState({
            loading: true,
            saving: false,
            info: null,

            // Atributos que formarán los dos ejes de la matriz.
            rowAttribute: null,
            columnAttribute: null,

            // Valores dinámicos de cada atributo.
            rows: [],
            columns: [],

            // Relación:
            // fila + columna -> product.product
            cellProducts: {},

            // Cantidades ingresadas por variante.
            quantities: {},
        });

        this.lineId = this.props.action.params.line_id;

        onWillStart(async () => {
            try {
                const info = await this.orm.call(
                    "dt.store.transfer.line",
                    "get_variant_distribution_info",
                    [[this.lineId]]
                );

                this.state.info = info;

                // Construir la matriz con los atributos reales del producto.
                this.prepareMatrix();

            } catch (error) {
                this.notification.add(
                    error.message ||
                        "No se pudo cargar la distribución por variantes.",
                    {
                        type: "danger",
                        title: "Distribución de variantes",
                    }
                );
            } finally {
                this.state.loading = false;
            }
        });
    }

    // ============================================================
    // CONSTRUIR MATRIZ DINÁMICA
    //
    // No se utilizan nombres fijos como Color, Talla, S, M, etc.
    // Se toman directamente los atributos y valores de Odoo.
    // ============================================================
    prepareMatrix() {
        const info = this.state.info;

        if (!info || !info.variants || !info.variants.length) {
            return;
        }

        const firstVariant = info.variants[0];

        if (!firstVariant.attributes || firstVariant.attributes.length < 2) {
            return;
        }

        const firstAttribute = firstVariant.attributes[0];
        const secondAttribute = firstVariant.attributes[1];

        this.state.rowAttribute = {
            id: firstAttribute.attribute_id,
            name: firstAttribute.attribute_name,
        };

        this.state.columnAttribute = {
            id: secondAttribute.attribute_id,
            name: secondAttribute.attribute_name,
        };

        const rowValues = new Map();
        const columnValues = new Map();
        const cellProducts = {};
        const quantities = {};

        // --------------------------------------------------------
        // Recorrer todas las variantes reales del producto.
        // --------------------------------------------------------
        for (const variant of info.variants) {
            const rowValue = variant.attributes.find(
                (attribute) =>
                    attribute.attribute_id ===
                    this.state.rowAttribute.id
            );

            const columnValue = variant.attributes.find(
                (attribute) =>
                    attribute.attribute_id ===
                    this.state.columnAttribute.id
            );

            if (!rowValue || !columnValue) {
                continue;
            }

            rowValues.set(rowValue.value_id, {
                id: rowValue.value_id,
                name: rowValue.value_name,
            });

            columnValues.set(columnValue.value_id, {
                id: columnValue.value_id,
                name: columnValue.value_name,
            });

            // Clave única para identificar cada celda.
            const cellKey =
                `${rowValue.value_id}_${columnValue.value_id}`;

            cellProducts[cellKey] = variant.product_id;

            quantities[variant.product_id] = 0;
        }

        // --------------------------------------------------------
        // Recuperar una distribución previamente guardada.
        // --------------------------------------------------------
        for (const item of info.distribution || []) {
            if (item.product_id) {
                quantities[item.product_id] =
                    Number(item.qty || item.quantity || 0);
            }
        }

        this.state.rows = Array.from(rowValues.values());
        this.state.columns = Array.from(columnValues.values());
        this.state.cellProducts = cellProducts;
        this.state.quantities = quantities;
    }

    // ============================================================
    // OBTENER PRODUCTO DE UNA CELDA
    // ============================================================
    getProductId(rowId, columnId) {
        const key = `${rowId}_${columnId}`;

        return this.state.cellProducts[key] || false;
    }

    // ============================================================
    // ACTUALIZAR CANTIDAD
    // ============================================================
    updateQuantity(productId, event) {
        if (!productId) {
            return;
        }

        let quantity = Number(event.target.value || 0);

        if (quantity < 0) {
            quantity = 0;
        }

        this.state.quantities[productId] = quantity;
    }

    // ============================================================
    // TOTAL DISTRIBUIDO
    // ============================================================
    get distributedTotal() {
        return Object.values(this.state.quantities).reduce(
            (total, quantity) => total + Number(quantity || 0),
            0
        );
    }

    // ============================================================
    // DIFERENCIA CONTRA LO ENVIADO
    // ============================================================
    get difference() {
        if (!this.state.info) {
            return 0;
        }

        return Number(this.state.info.qty_sent || 0) -
            this.distributedTotal;
    }

    // ============================================================
    // GUARDAR DISTRIBUCIÓN
    // ============================================================
    async saveDistribution() {

        // La distribución debe coincidir exactamente con lo enviado.
        if (Math.abs(this.difference) > 0.000001) {
            this.notification.add(
                "La cantidad distribuida debe ser igual a la cantidad enviada.",
                {
                    type: "warning",
                    title: "Distribución incompleta",
                }
            );
            return;
        }

        const distribution = [];

        // Solo enviar al backend las variantes con cantidad mayor a cero.
        for (const [productId, quantity] of Object.entries(
            this.state.quantities
        )) {
            const qty = Number(quantity || 0);

            if (qty > 0) {
                distribution.push({
                    product_id: Number(productId),
                    qty: qty,
                });
            }
        }

        this.state.saving = true;

        try {
            await this.orm.call(
                "dt.store.transfer.line",
                "save_variant_distribution",
                [[this.lineId], distribution]
            );

            // Mantener sincronizada la información visible.
            this.state.info.distribution = distribution;
            this.state.info.qty_received = this.distributedTotal;

            this.notification.add(
                "La distribución por variantes fue guardada correctamente.",
                {
                    type: "success",
                    title: "Distribución guardada",
                }
            );

        } catch (error) {
            this.notification.add(
                error.message ||
                    "No se pudo guardar la distribución por variantes.",
                {
                    type: "danger",
                    title: "Error al guardar",
                }
            );
        } finally {
            this.state.saving = false;
        }
    }
}

registry.category("actions").add(
    "dt_variant_distribution",
    VariantDistributionAction
);