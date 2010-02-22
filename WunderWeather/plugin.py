###
# Copyright (c) 2005, James Vega
# Copyright (c) 2009, Michael Tughan
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
#   * Redistributions of source code must retain the above copyright notice,
#     this list of conditions, and the following disclaimer.
#   * Redistributions in binary form must reproduce the above copyright notice,
#     this list of conditions, and the following disclaimer in the
#     documentation and/or other materials provided with the distribution.
#   * Neither the name of the author of this software nor the name of
#     contributors to this software may be used to endorse or promote products
#     derived from this software without specific prior written consent.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED.  IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
###

import xml.dom.minidom as dom

import supybot.utils as utils
from supybot.commands import *
import supybot.plugins as plugins
import supybot.ircutils as ircutils
import supybot.callbacks as callbacks

import shortforms
reload(shortforms)

noLocationError = 'No such location could be found.'
class NoLocation(callbacks.Error):
    pass

class WunderWeather(callbacks.Plugin):
    """Uses the Wunderground XML API to get weather conditions for a given
    location. Always gets current conditions, and by default shows a 7-day
    forecast as well."""
    threaded = True
    def _noLocation():
        raise NoLocation, noLocationError
    _noLocation = staticmethod(_noLocation)

    _weatherCurrentCondsURL = 'http://api.wunderground.com/auto/wui/geo/' \
                              'WXCurrentObXML/index.xml?query=%s'
    _weatherForecastURL = 'http://api.wunderground.com/auto/wui/geo/' \
                          'ForecastXML/index.xml?query=%s'
    def weather(self, irc, msg, args, location):
        """<US zip code | US/Canada city, state | Foreign city, country>

        Returns the approximate weather conditions for a given city from
        Wunderground.
        """
        channel = None
        if irc.isChannel(msg.args[0]):
            channel = msg.args[0]
        if not location:
            location = self.userValue('lastLocation', msg.prefix)
        if not location:
            raise callbacks.ArgumentError
        self.setUserValue('lastLocation', msg.prefix,
                          location, ignoreNoUser=True)
        
        # Check for shortforms, because Wunderground will attempt to check
        # for US locations without a full country name.
        
        # checkShortforms may return Unicode characters in the country name.
        # Need Latin 1 for Supybot's URL handlers to work
        webLocation = shortforms.checkShortforms(location)
        conditions = self._getDom(self._weatherCurrentCondsURL % 
                                  utils.web.urlquote(webLocation))
        observationLocation = conditions.getElementsByTagName(
                                  'observation_location')[0]
        
        # if there's no city name in the XML, we didn't get a match
        if observationLocation.getElementsByTagName('city')[0].childNodes.length < 1:
            # maybe the country shortform given conflicts with a state
            # shortform and wasn't replaced before
            webLocation = shortforms.checkConflictingShortforms(location)
            
            # if no conflicting short names match,
            # we have the same query as before
            if webLocation == None:
                self._noLocation()
            
            conditions = self._getDom(self._weatherCurrentCondsURL %
                                      utils.web.urlquote(webLocation))
            observationLocation = conditions.getElementsByTagName(
                                      'observation_location')[0]
            
            # if there's still no match, nothing more we can do
            if observationLocation.getElementsByTagName('city')[0].childNodes.length < 1:
                self._noLocation()
        
        forecast = self._getDom(self._weatherForecastURL %
                                utils.web.urlquote(webLocation))
        
        output = []
        
        output.append(u'Weather for ' + self._getNodeValue(conditions, 'full',
                                                          'Unknown Location'))
        
        output.append(self._getCurrentConditions(conditions, channel))
        # _getForecast returns a list, so we have to
        # call extend rather than append
        output.extend(self._getForecast(forecast, channel))
        
        # UTF-8 encoding is required for Supybot to handle \xb0 (degrees) and
        # other special chars. We can't (yet) pass it a Unicode string on its
        # own (an oddity, to be sure)
        irc.reply(u' | '.join(output).encode('utf-8'))
    weather = wrap(weather, [additional('text')])
    
    def _getCurrentConditions(self, dom, channel):
        output = []
        
        temp = self._formatCurrentConditionTemperatures(dom, 'temp', channel)
        if self._getNodeValue(dom, 'heat_index_string') != 'NA':
            temp += u' (Heat Index: %s)' %
                self._formatCurrentConditionTemperatures(dom, 'heat_index',
                                                         channel)
        if self._getNodeValue(dom, 'windchill_string') != 'NA':
            temp += u' (Wind Chill: %s)' %
                self._formatCurrentConditionTemperatures(dom, 'windchill',
                                                         channel)
        output.append(u'Temperature: ' + temp)
        
        output.append(u'Humidity: ' +
            self._getNodeValue(dom, 'relative_humidity', u'N/A%'))
        
        output.append(u'Pressure: ' +
            self._formatPressures(dom, channel))
        
        output.append(u'Conditions: ' +
            self._getNodeValue(dom, 'weather'))
        
        output.append(u'Wind Direction: ' +
            self._getNodeValue(dom, 'wind_dir', u'None'))
        
        output.append(u'Wind Speed: ' +
            self._formatSpeeds(dom, 'wind_mph', channel))
        
        output.append(u'Updated: ' +
            self._getNodeValue(dom, 'observation_time').lstrip(u'Last Updated on '))
        
        return u'; '.join(output)
    
    def _getForecast(self, dom, channel):
        if not self.registryValue('showForecast'):
            return []
        output = []
        count = 0
        max = self.registryValue('forecastDays', channel)
        
        forecast = dom.getElementsByTagName('simpleforecast')[0]
        
        for day in forecast.getElementsByTagName('forecastday'):
            if count >= max and max != 0:
                break
            forecastOutput = []
            
            forecastOutput.append('Forecast for ' + self._getNodeValue(day, 'weekday'))
            
            forecastOutput.append('Conditions: ' + self._getNodeValue(day, 'conditions'))
            forecastOutput.append('High: ' + self._formatForecastTemperatures(day, 'high', channel))
            forecastOutput.append('Low: ' + self._formatForecastTemperatures(day, 'low', channel))
            output.append('; '.join(forecastOutput))
            count += 1
        return output
    
    
    # format temperatures using _formatForMetricOrImperial
    def _formatCurrentConditionTemperatures(self, dom, string, channel):
        tempC = self._getNodeValue(dom, string + '_c', u'N/A') + u'\xb0C'
        tempF = self._getNodeValue(dom, string + '_f', u'N/A') + u'\xb0F'
        return self._formatForMetricOrImperial(tempF, tempC, channel)
    
    def _formatForecastTemperatures(self, dom, type, channel):
        tempC = self._getNodeValue(dom.getElementsByTagName(type)[0], 'celsius', u'N/A') + u'\xb0C'
        tempF = self._getNodeValue(dom.getElementsByTagName(type)[0], 'fahrenheit', u'N/A') + u'\xb0F'
        return self._formatForMetricOrImperial(tempF, tempC, channel)
    
    def _formatSpeeds(self, dom, string, channel):
        mphValue = float(self._getNodeValue(dom, string, u'0'))
        speedM = u'%dmph' % round(mphValue)
        # thanks Wikipedia for the conversion rate for miles -> km/h
        speedK = u'%dkm/h' % round(mphValue * 1.609344)
        return self._formatForMetricOrImperial(speedM, speedK, channel)
    
    def _formatPressures(self, dom, channel):
        # lots of function calls, but it just divides pressure_mb by 10
        # and rounds it to change hPa into kPa
        pressureKpa = str(round(float(self._getNodeValue(dom, 'pressure_mb',
                                          u'0')) / 10, 1)) + 'kPa'
        pressureIn = self._getNodeValue(dom, 'pressure_in', u'0') + 'in'
        return self._formatForMetricOrImperial(pressureIn, pressureKpa, channel)
    
    # formats any imperial or metric values according to the config
    def _formatForMetricOrImperial(self, imperial, metric, channel):
        showM = self.registryValue('metric', channel)
        showI = self.registryValue('imperial', channel)
        returnValues = []
        
        if showI:
            returnValues.append(imperial)
        if showM:
            returnValues.append(metric)
        
        if returnValues == []:
            returnValues = (imperial, metric)
        
        return u'/'.join(returnValues)
    
    def _getDom(self, url):
        xmlString = utils.web.getUrl(url)
        return dom.parseString(xmlString)
    
    def _getNodeValue(dom, value, default=u'Unknown'):
        subTag = dom.getElementsByTagName(value)
        if len(subTag) < 1:
            return default
        subTag = subTag[0].firstChild
        if subTag == None:
            return default
        return subTag.nodeValue
    _getNodeValue = staticmethod(_getNodeValue)

Class = WunderWeather


# vim:set shiftwidth=4 softtabstop=4 expandtab textwidth=79:
