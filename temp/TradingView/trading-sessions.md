# Trading Sessions

**Source:** <https://www.tradingview.com/support/solutions/43000729030-trading-sessions/>  
**Indicator ID:** 43000729030  
**Slug:** `trading-sessions`

[← back to index](./README.md)

---

The Trading Sessions indicator highlights custom trading sessions on the chart. For each trading session, the indicator draws a colored box containing all the bars that  _opened_ within the session in the specified time zone. Users can customize up to three trading sessions with unique start and end times and time zones. The default settings represent commonly used Asian, European, and North American sessions (Tokyo, London, and New York).

  


Instruments that are traded in multiple markets in different time zones can experience periodic spikes in volume and volatility. Using the Trading Sessions indicator, users can visually track when different markets open and close.

Note that the Trading Sessions indicator is available only on  _intraday_ timeframes.

![](https://s3.amazonaws.com/cdn.freshdesk.com/data/helpdesk/attachments/production/43556707726/original/zdh-Wd55MzLxGHvwYphOxUrrvccU_Jdg1Q.png?1746720113)

#### Inputs

The indicator’s inputs define the trading session’s timings, and include options to display additional price information about each session.

![](https://s3.amazonaws.com/cdn.freshdesk.com/data/helpdesk/attachments/production/43556708118/original/C6UKS0tTU8emaupNosJmLrAl-ZUR6O8Ufg.png?1746720204)

#### General settings

There are four toggles at the top of the indicator’s Inputs tab, which provide general settings that apply to  _all three_ trading sessions. These settings determine the text information and additional visuals displayed for each session:

  * "Show session names": Labels each session box with the text from its "Displayed name" setting.
  * "Draw session open and close lines": Draws two additional dashed lines within each session box to mark the open and close prices of the session (i.e., the first bar’s open and the last bar’s close).
  * "Show tick range for each session": Calculates the number of ticks between the highest and lowest prices within the session and displays the range value in a label below the session box.
  * "Show average price per session": Calculates the average close price for all bars within the session and displays it in a label below the session box. It also draws a dotted line within the session box at the average price.



#### Session settings

The following inputs determine the settings for a specific trading session. The _"__First session"_ , _"__Second session"_ , and _"__Third session"_ input sections each have the same settings.

#### Show session

Specifies whether the indicator displays this trading session. If it is unchecked, the session is hidden from the chart.

#### Displayed name

Specifies the name of the session. The default value corresponds to the session’s default time zone, but users can enter any text of their choice to label the session.

The session’s name appears on the chart below each session box only when the "Show session names" input is selected. Otherwise, the session’s name is hidden from the chart.

#### Session time

Specifies the start and end times of the session. The input’s dropdown list shows the time options in 15-minute intervals. To use a time that falls outside these intervals, select the minutes value in the input field and type the desired number.

If the session’s end time is earlier than its start time, the indicator considers it an  _overnight_ session. For example, the session time "10:00–09:00" highlights bars from 10AM on the first day to 9AM on the second day.

#### Session time zone

Specifies the time zone for the session’s start and end times. 

There are two supported formats for a session's time zone:

  * _GMT (or UTC) notation_ , which uses a numerical offset from the[ Greenwich Mean Time](<https://en.wikipedia.org/wiki/Greenwich_Mean_Time>) or[ Coordinated Universal Time](<https://en.wikipedia.org/wiki/Coordinated_Universal_Time>), e.g., "GMT-5", "GMT+0630", "UTC+11".
  * _IANA database notation_ , which uses a regional identifier, e.g., "America/New_York", "Asia/Tokyo", "Europe/Paris". See the[ IANA time zone database](<https://en.wikipedia.org/wiki/List_of_tz_database_time_zones>) reference page for the list of possible time zone identifiers and their respective GMT offsets.



If the time zone field is left empty, the indicator uses the IANA time zone from the exchange of the symbol that is currently open on the chart.

#### Session color

Sets the color and opacity of the session box and any related text or lines displayed for this session (e.g., session name, average price line, etc.).

#### Considerations for time zone changes

Using the IANA time zone notation is a more robust way to specify a session’s time zone than using a fixed GMT notation. We recommend using the IANA notation in most cases because it automatically adjusts for a region’s local time policies, such as annual switches to[ daylight saving time (DST)](<https://en.wikipedia.org/wiki/Daylight_saving_time>), and it also accounts for historic and future updates to time zone boundaries.

To demonstrate, let's look at a "BINANCE:BTCUSD" chart; the symbol’s exchange uses a fixed GMT(0) time zone throughout the year. Using the Trading Sessions indicator, we can compare two different sessions that both represent the typical New York trading hours: "09:30–16:00". The first trading session uses "GMT-4" as its time zone, highlighting its session bars in a blue box. The second session uses the "America/New_York" time zone notation, highlighting its session bars in a yellow box.

Since both sessions are meant to represent the same period in the same local time zone, the session boxes should always align perfectly. However, the session boxes do diverge periodically.

![](https://s3.amazonaws.com/cdn.freshdesk.com/data/helpdesk/attachments/production/43556708374/original/MElTLsEMQl_En4kDEtcz4jPbWsq06RKXKw.png?1746720281)

During daylight saving time (DST), both the "GMT" and "IANA" trading sessions overlap exactly. During the rest of the year, however, the two sessions differ by one hour because New York’s local time switches from GMT-4 to GMT-5 outside of DST. The "America/New_York" notation automatically adjusts for this time zone change, but the "GMT-4" offset remains fixed.

As a result, using the "America/New_York" notation  _always_ highlights the "09:30–16:00" sessions correctly in the region’s local time, while using the "GMT-4" notation highlights the sessions correctly  _only_ during DST. Likewise, using a "GMT-5" time zone instead highlights the sessions correctly  _only_ in the non-DST period, and deviates by one hour during DST.

Therefore, to avoid needing to manually adjust GMT offsets for regions that experience time zone changes, use the IANA time zone notation to represent regional time zones accurately at any time of the year.

PreviousPrevious

Total UTXOs

NextNext

Transaction fees

Launch Supercharts

---

[← back to index](./README.md)
