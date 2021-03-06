/*
gw2copilot/js/live_edit_modal.js

The latest version of this package is available at:
<https://github.com/jantman/gw2copilot>

################################################################################
Copyright 2016 Jason Antman <jason@jasonantman.com> <http://www.jasonantman.com>

    This file is part of gw2copilot.

    gw2copilot is free software: you can redistribute it and/or modify
    it under the terms of the GNU Affero General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    gw2copilot is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU Affero General Public License for more details.

    You should have received a copy of the GNU Affero General Public License
    along with gw2copilot.  If not, see <http://www.gnu.org/licenses/>.

The Copyright and Authors attributions contained herein may not be removed or
otherwise altered, except to add the Author attribution of a contributor to
this work. (Additional Terms pursuant to Section 7b of the AGPL v3)
################################################################################
While not legally required, I sincerely request that anyone who finds
bugs please submit them at <https://github.com/jantman/gw2copilot> or
to me via email, and that you send any contributions or improvements
either as a pull request on GitHub, or to me via email.
################################################################################

AUTHORS:
Jason Antman <jason@jasonantman.com> <http://www.jasonantman.com>
################################################################################
*/

// BEGIN building drop-down choices array

// array to hold the choices for the zone selection dropdowns on edit modal
zone_options = [ { value: 0, label: '{Select a Zone}' } ];

// main.js provides sortProperties()
sortProperties(WORLD_ZONES_IDtoNAME).map( function(item) {
    // item is an array of [key (map_id), value (map_name)]
    zone_options.push({ value: item[0], label: item[1]});
});
// END building drop-down choices array

// appendGrid for Edit Zone Reminders modal
$(function () {
    $('#zoneRemindersTable').appendGrid({
        initRows: 1,
        columns: [
            { name: 'map_id', display: 'Zone', type: 'select', ctrlOptions: zone_options, ctrlCss: { width: '100%' } },
            { name: 'text', display: 'Reminder Text', type: 'text', ctrlCss: { width: '100%' } },
            { name: 'id', type: 'hidden', value: 0 }
        ],
        hideButtons: {
            removeLast: true,
            moveUp: true,
            moveDown: true,
            insert: true
        },
        customGridButtons: {
            append: function() { return $('<button/>').attr({ type: 'button' }).append('<span class="ui-button-icon-primary ui-icon ui-icon-plusthick"></span>', '<span class="ui-button-text"></span>'); },
            remove: function() { return $('<button/>').attr({ type: 'button' }).append('<span class="ui-button-icon-primary ui-icon ui-icon-trash"></span>', '<span class="ui-button-text"></span>'); }
        }
    });
});

/**
 * Handle the "edit reminders" link modal
 */
function handleEditReminders() {
    // populate the appendGrid table
    $.ajax({
        url: "/api/zone_reminders"
    }).done(function( data ){
        data = JSON.parse(data);
        if ( data.length > 0 ) {
            $('#zoneRemindersTable').appendGrid('load', data);
            makeZoneRemindersCache(data);
        }
        $("#remindersModal").modal("show");
    });
    return false;
}

/**
 * Handle the "Save" button on the Edit Reminders modal
 */
$('#saveZoneRemindersTable').click(function () {
    data = [];
    $('#remindersModal tbody tr')
      .each(function( index ) {
          d = {
              'map_id': $(this).find('select').first().find(':selected').val(),
              'text': $.trim($(this).find('input').first().val())
          };
          if ( d['map_id'] != 0 && d['text'] != '' ) { data.push(d); }
    });
    if ( data.length == 0 ) { return false; }
    s = JSON.stringify(data);
    $.ajax({
        url: '/api/zone_reminders',
        type: 'PUT',
        data: s,
        success: function(d) {
            $("#remindersModal").modal("hide");
            makeZoneRemindersCache(data);
        }
    });
});

/**
 * Get zone reminders from API; update the cache at ``P.zone_reminders``.
 */
function getZoneRemindersFromAPI() {
    $.ajax({
        url: "/api/zone_reminders"
    }).done(function( data ){
        data = JSON.parse(data);
        if ( data.length > 0 ) {
            makeZoneRemindersCache(data);
        }
    });
}

/**
 * Update the in-memory zone reminders object, from the list of reminders.
 *
 * @param {array} rlist - list of reminder objects, as seen in
 *   ``handleEditReminders()`` and ``$('#saveZoneRemindersTable').click()``
 */
function makeZoneRemindersCache(rlist) {
    c = {};
    rlist.map( function(item) {
        // item is the reminder object
        if ( ! c.hasOwnProperty(item["map_id"]) ) { c[item["map_id"]] = []; }
        c[item["map_id"]].push(item["text"]);
    });
    P.zone_reminders = c;
    if ( typeof P !== 'undefined' && P.hasOwnProperty("map_id") ) {
        doZoneReminder(P.map_id);
    }
}
