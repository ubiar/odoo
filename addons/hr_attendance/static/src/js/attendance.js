
openerp.hr_attendance = function (instance) {
    
    var QWeb = instance.web.qweb;
    var _t = instance.web._t;
    var _lt = instance.web._lt;

    instance.hr_attendance.AttendanceSlider = instance.web.Widget.extend({
        template: 'AttendanceSlider',
        init: function (parent) {
            this._super(parent);
            this.set({"signed_in": false});
        },
        start: function() {
            var self = this;
            var tmp = function() {
                var signed_in = this.get("signed_in");
                var $sign_in_out_icon = this.$('#oe_attendance_sign_in_out_icon');
                $sign_in_out_icon.toggleClass("fa-sign-in", ! signed_in);
                $sign_in_out_icon.toggleClass("fa-sign-out", signed_in);
                this.$el.toggleClass("oe_fichaje_dentro", signed_in);
                this.$el.toggleClass("oe_fichaje_fuera", ! signed_in);
                this.$('.oe_attendance_status_text').text(signed_in ? _t("Salir") : _t("Ingresar"));
            };
            this.on("change:signed_in", this, tmp);
            _.bind(tmp, this)();
            this.$(".oe_attendance_sign_in_out").click(function(ev) {
                ev.preventDefault();
                self.do_update_attendance();
            });
            this.$el.tooltip({
                title: function() {
                    var last_text = instance.web.format_value(self.last_sign, {type: "datetime"});
                    var duration = self.last_sign ? $.timeago(self.last_sign) : "none";
                    if (self.get("signed_in")) {
                        return _.str.sprintf(_t("Last sign in: %s,<br />%s.<br />Click to sign out."), last_text, duration);
                    } else if (self.last_sign) {
                        return _.str.sprintf(_t("Última salida: %s (%s).<br />Click para ingresar."), last_text, duration);
                    } else {
                        return _t("Click para ingresar.");
                    }
                },
            });
            return this.check_attendance();
        },
        do_update_attendance: function () {
            var self = this;
            var action = self.get("signed_in") ? 'sign_out' : 'sign_in';
            new instance.web.Model('hr.employee').call('attendance_action_change', [
                [self.employee.id]
            ], {context: {action: action}}).done(function (result) {
                self.last_sign = new Date();
                self.set({"signed_in": ! self.get("signed_in")});
            }).fail(function (error, event) {
                // El estado real difiere del que muestra el botón: evitamos el error
                // genérico, avisamos qué acción ya existía y resincronizamos el botón.
                if (event) { event.preventDefault(); }
                var titulo = action === 'sign_in' ? _t("Ya existe una Entrada.") : _t("Ya existe una Salida.");
                self.do_warn(titulo, _t("Se actualizó el botón de marcación."));
                self.check_attendance();
            });
        },
        check_attendance: function () {
            var self = this;
            self.employee = false;
            this.$el.hide();
            var employee = new instance.web.DataSetSearch(self, 'hr.employee', self.session.user_context, [
                ['user_id', '=', self.session.uid]
            ]);
            return employee.read_slice(['id', 'name', 'state', 'last_sign', 'attendance_access']).then(function (res) {
                if (_.isEmpty(res) )
                    return;
                if (res[0].attendance_access === false){
                    return;
                }
                self.$el.show();
                self.employee = res[0];
                self.last_sign = instance.web.str_to_datetime(self.employee.last_sign);
                self.set({"signed_in": self.employee.state !== "absent"});
            });
        },
    });

    // Put the AttendanceSlider widget in the systray menu if the user is an employee
    var Users = new instance.web.Model('res.users');
    Users.call('has_group', ['base.group_user']).done(function(is_employee) {
        if (is_employee) {
            instance.web.SystrayItems.push(instance.hr_attendance.AttendanceSlider);
        }
    })
};
