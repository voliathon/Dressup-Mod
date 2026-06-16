-- Copyright © 2013-2026, Cairthenn/Voliathon
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

function get_item_id(str, slot, arg2)
    if not str then return false end
    if str:lower() == "none" then return "None" end

    local wants_ag = (arg2 == "ag" or arg2 == "afterglow")
    local search_str = str:lower()
    local fallback_item_id = false
    
    for k, v in pairs(models[slot]) do
        local enl = v['enl'] and v['enl']:lower() or ""
        local name = v['name'] and v['name']:lower() or ""
        
        if enl == search_str or name == search_str then
            if wants_ag then
                if v['afterglow'] then
                    return tonumber(k)
                end
            else
                if not v['afterglow'] then
                    return tonumber(k)
                end
            end
            
            -- Save this as a fallback if we don't find the exact afterglow requirement
            fallback_item_id = k
        end
    end

    return fallback_item_id and tonumber(fallback_item_id) or false
end

function update_model(index)
    -- Relies on 'packets' being a global variable from DressUp.lua
    if packets then
        packets.inject(packets.new('outgoing', 0x016, { ['Target Index'] = index }))
    end
end

function load_profile(name)
    if not name then return false end

    local player_name = windower.ffxi.get_player().name:lower()
    local profile_name = name:lower()
    local specific_profile = player_name .. '_' .. profile_name

    if settings.profiles[specific_profile] then
        settings[player_name]:update(settings.profiles[specific_profile])
        return true
    elseif settings.profiles[profile_name] then
        settings[player_name]:update(settings.profiles[profile_name])
        return true
    end
    
    return false
end

function save_profile(name)
    if type(name) ~= 'string' or name:len() == 0 then 
        error('No profile name was entered.') 
        return
    end
    
    local player_name = windower.ffxi.get_player().name:lower()
    local profile_name = name:lower()

    if not settings.profiles[profile_name] then 
        settings.profiles[profile_name] = T{} 
    end    
    
    settings.profiles[profile_name]:update(settings[player_name])
    notice('Saved your current settings to the profile: ' .. name)
end

function blink_logic(blink_type, character_index, player)
    local all_blink = settings.blinking["all"]
    local specific_blink = settings.blinking[blink_type]

    if all_blink["always"] or specific_blink["always"] then
        return true
    end
    
    if player.in_combat and (all_blink["combat"] or specific_blink["combat"]) then
        return true
    end

    if player.target_index == character_index and (all_blink["target"] or specific_blink["target"]) then
        return true
    end
    
    return false
end

-- Helper table mapping logic for settings output
local function map(t, func)
    local out = {}
    for k, v in pairs(t) do
        out[#out + 1] = func(k, v)
    end
    return out
end

local function formatting(k, v) 
    local display_val = 'F'
    local val_str = tostring(v):lower()
    
    if val_str == "true" then
        display_val = ('T'):text_color(0, 255, 0)
    end
    
    return k:gsub("^%l", string.upper) .. ': [' .. display_val .. ']' 
end

function print_blink_settings(option)
    print('DressUp (v' .. _addon.version .. ') Blink Prevention Settings') 
    
    if option == "global" or option == "all" then
        print(('All:    '):text_color(255, 255, 255) .. table.concat(map(settings.blinking["all"], formatting), " "))
    end
    if option == "global" or option == "self" then
        print(('Self:   '):text_color(255, 255, 255) .. table.concat(map(settings.blinking["self"], formatting), " "))
    end
    if option == "global" or option == "others" then
        print(('Others: '):text_color(255, 255, 255) .. table.concat(map(settings.blinking["others"], formatting), " "))
    end
    if option == "global" or option == "party" then
        print(('Party:  '):text_color(255, 255, 255) .. table.concat(map(settings.blinking["party"], formatting), " "))
    end
    if option == "global" or option == "follow" then
        print(('Follow: '):text_color(255, 255, 255) .. table.concat(map(settings.blinking["follow"], formatting), " "))
    end
end