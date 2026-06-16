-- Copyright © 2013-2017, Cairthenn
-- All rights reserved.

-- Redistribution and use in source and binary forms, with or without
-- modification, are permitted provided that the following conditions are met:

    -- * Redistributions of source code must retain the above copyright
      -- notice, this list of conditions and the following disclaimer.
    -- * Redistributions in binary form must reproduce the above copyright
      -- notice, this list of conditions and the following disclaimer in the
      -- documentation and/or other materials provided with the distribution.
    -- * Neither the name of DressUp nor the
      -- names of its contributors may be used to endorse or promote products
      -- derived from this software without specific prior written permission.

-- THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
-- ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
-- WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
-- DISCLAIMED. IN NO EVENT SHALL Cairthenn BE LIABLE FOR ANY
-- DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
-- (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
-- LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND
-- ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
-- (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
-- SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

_addon.name = 'DressUp'
_addon.author = 'Cair'
_addon.version = '1.40'
_addon.commands = {'DressUp','du'}


packets = require('packets')
require('luau')
require('helper_functions')
require('static_variables')


models = {}
require('main')
require('sub')
require('head')
require('body')
require('hands')
require('legs')
require('feet')
require('ranged')

settings = config.load(defaults)


model_names = S{"Face","Race","Head","Body","Hands","Legs","Feet","Main","Sub","Ranged"}

local initialize = function()
    local player = windower.ffxi.get_player()
    info.self.name = player.name:lower()
    info.self.id = player.id
    info.self.index = player.index

    if not settings[info.self.name] then
        settings[info.self.name] = {}
    end

    print_blink_settings("global")
    if load_profile(player.main_job) then
        notice('Loaded profile: ' .. player.main_job)
    elseif load_profile(player.main_job_full) then
        notice('Loaded profile: ' .. player.main_job_full)
    end

    update_model(info.self.index)
end

windower.register_event('load', function()
    if windower.ffxi.get_info().logged_in then
        initialize()
    end
end)

windower.register_event('login', initialize)

windower.register_event('logout', function()
    info.self:clear()
end)

windower.register_event('job change',function(job)
    if load_profile(res.jobs[job].name_short) then
        update_model(info.self.index)
        notice('Loaded profile: ' .. res.jobs[job].name_short)
    elseif load_profile(res.jobs[job].name) then
        update_model(info.self.index)
        notice('Loaded profile: ' .. res.jobs[job].name)
    end
end)


local modify_gear = function(packet, name, freeze, models)
    local modified = false

    for k, v in pairs(packet) do
        if model_names[k] then
            if rawget(settings, name) and settings[name][k:lower()] then
                -- Settings for individuals
                packet[k] = settings[name][k:lower()]
                modified = true
            elseif table.containskey(settings.replacements[k:lower()], tostring(v)) then
                -- Replace specific gear
                packet[k] = settings.replacements[k:lower()][tostring(v)]
                modified = true
            elseif freeze and models and models[k] then
                -- Swap the model values from memory to the packet to prevent blinking
                packet[k] = models[k]
                modified = true
            end
        end
    end  

    return modified, packet
end

windower.register_event('incoming chunk',function (id, _, data)
    
    if id ~= 0x00A and id ~= 0x00D and id ~= 0x051 then
        return
    end

    local packet = packets.parse('incoming', data)
    local modified

    -- Processing based on packet type
    if id == 0x00A then
        info.self.id = packet['Player']
        info.self.index = packet['Player Index']
        info.self.name = packet['Player Name']:lower()
        modified,packet = modify_gear(packet, info.self.name)
        return modified and packets.build(packet)
    end

    if id == 0x0D and not packet['Update Model'] then
        return
    end

    local char_id = packet.Player or info.self.id
    local char_index = packet.Index or info.self.index
    local character = windower.ffxi.get_mob_by_index(char_index or -1)
    local blink_type, name = 'others'
    local models

    if character and character.models and table.length(character.models) == 9 and
        (id == 0x051 or (id == 0x00D and character.id == packet.Player) ) then
        models = T{
            Race    = character.race,
            Face    = character.models[1],
            Head    = character.models[2]+0x1000,
            Body    = character.models[3]+0x2000,
            Hands   = character.models[4]+0x3000,
            Legs    = character.models[5]+0x4000,
            Feet    = character.models[6]+0x5000,
            Main    = character.models[7]+0x6000,
            Sub     = character.models[8]+0x7000,
            Ranged  = character.models[9]+0x8000}
    end

    if not info.names[char_id] then
        if packet['Update Name'] then
            info.names[char_id] = packet['Character Name']:lower()
        elseif character then
            info.names[char_id] = character.name:lower()
        else
            return
        end
    end

    local player = windower.ffxi.get_player()

    if player.follow_index == char_index then
        blink_type = "follow"
    elseif character and character.in_alliance then
        blink_type = "party"
    else
        blink_type = "others"
    end

    if info.names[char_id] == info.self.name then
        name = info.self.name
        blink_type = "self"
    elseif settings[info.names[char_id]] then
        name = info.names[char_id]
    else
        name = "others"
    end
    
    -- Model ID 0xFFFF in ranged slot signifies a monster. This prevents undesired results.
    modified,packet = modify_gear(packet, name, blink_logic(blink_type, char_index, player), models)
    return packet['Ranged'] ~= 0xFFFF and modified and packets.build(packet)
end)

--[[windower.register_event('outgoing chunk',function (id, data)
    if id == 0x17 then
        -- Block the NPC/armor mismatch error packet
        return true
    end
end)
-- It appear that blocking this packet might have been causing people to not show up occasionally.
-- Rather than an unnatural error packet, it might be a normal part of client-server communication.]]

windower.register_event('addon command', function (command,...)
    command = command and command:lower() or 'help'
    local args = T{...}:map(string.lower)
    local _clear = nil
    
    if command == 'help' then
        print(helptext)
